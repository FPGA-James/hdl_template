#!/usr/bin/env python3
"""Register generation script for the HDL template.

Parses all TOML register definitions in regs/ and generates:
  - VHDL register constants package       → out/regs/vhdl/
  - VHDL typed record package             → out/regs/vhdl/
  - VHDL AXI-Lite register file wrapper   → out/regs/vhdl/
  - C header file                         → out/regs/c/
  - HTML register documentation           → out/regs/html/ (linked by Sphinx)

Run via: make regs
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from hdl_registers.parser.toml import from_toml
from hdl_registers.generator.vhdl.register_package import VhdlRegisterPackageGenerator
from hdl_registers.generator.vhdl.record_package import VhdlRecordPackageGenerator
from hdl_registers.generator.vhdl.axi_lite.wrapper import VhdlAxiLiteWrapperGenerator
from hdl_registers.generator.systemverilog.axi_lite.register_file import (
    SystemVerilogAxiLiteGenerator,
)
from hdl_registers.generator.c.header import CHeaderGenerator
from hdl_registers.generator.html.page import HtmlPageGenerator
from hdl_registers.field.bit_vector import BitVector


@dataclass
class Port:
    """A single entity/module port, as parsed from RTL source text."""

    name: str
    direction: str  # VHDL: "in"/"out"/"inout"   SV: "input"/"output"/"inout"
    type_str: str


def parse_vhdl_ports(core_file: Path) -> dict[str, Port]:
    """Parse the entity port clause of a VHDL core file."""
    text = core_file.read_text()
    text = re.sub(r"--.*", "", text)
    match = re.search(
        r"\bport\s*\((.*?)\)\s*;\s*end\s+entity", text, re.IGNORECASE | re.DOTALL
    )
    if not match:
        raise ValueError(f"No entity port clause found in {core_file}")

    ports: dict[str, Port] = {}
    for entry in re.split(r";", match.group(1)):
        entry = entry.strip()
        if not entry:
            continue
        port_match = re.match(r"(\w+)\s*:\s*(in|out|inout)\s+(.+)", entry, re.IGNORECASE)
        if not port_match:
            raise ValueError(f"Could not parse port declaration: {entry!r} in {core_file}")
        name, direction, type_str = port_match.groups()
        ports[name] = Port(name=name, direction=direction.lower(), type_str=type_str.strip())
    return ports


def parse_sv_ports(core_file: Path) -> dict[str, Port]:
    """Parse the module port list of a SystemVerilog core file."""
    text = core_file.read_text()
    text = re.sub(r"//.*", "", text)
    match = re.search(r"\bmodule\s+\S+.*?\)\s*;", text, re.DOTALL)
    if not match:
        raise ValueError(f"No module port clause found in {core_file}")
    header = match.group(0)

    # The port list is the LAST top-level (...) group before the final ';'
    # (the module may also have a preceding #( ... ) parameter block).
    close_idx = header.rfind(")")
    depth = 0
    open_idx = None
    for i in range(close_idx, -1, -1):
        if header[i] == ")":
            depth += 1
        elif header[i] == "(":
            depth -= 1
            if depth == 0:
                open_idx = i
                break
    if open_idx is None:
        raise ValueError(f"Unbalanced parentheses in module header of {core_file}")
    body = header[open_idx + 1 : close_idx]

    ports: dict[str, Port] = {}
    for entry in re.split(r",(?![^\[]*\])", body):
        entry = entry.strip()
        if not entry:
            continue
        port_match = re.match(r"(input|output|inout)\s+(.+?)\s+(\w+)$", entry)
        if not port_match:
            raise ValueError(f"Could not parse port declaration: {entry!r} in {core_file}")
        direction, type_str, name = port_match.groups()
        ports[name] = Port(name=name, direction=direction, type_str=type_str.strip())
    return ports


@dataclass
class FieldMapping:
    """A single register field, resolved to the core port it drives/receives."""

    register_name: str
    field_name: str
    field_type: type
    width: int
    direction: str  # "down" (host writes, core input) or "up" (host reads, core output)
    port_name: str
    needs_cast: bool  # VHDL only: True for BitVector fields (record type is `unsigned`)


def build_field_mappings(register_list) -> list[FieldMapping]:
    """Walk the register list and compute each field's expected core port name,
    direction, and whether a VHDL type cast is needed to reach that port."""
    mappings: list[FieldMapping] = []
    for register in register_list.register_objects:
        mode = register.mode.shorthand
        if mode in ("w", "r_w"):
            direction, suffix = "down", "_i"
        elif mode == "r":
            direction, suffix = "up", "_o"
        else:
            raise ValueError(
                f"Register '{register.name}' uses mode '{mode}', which the "
                "SystemVerilog register-file generator does not support "
                "(only r, w, r_w). Use a supported mode — see Task 1 of "
                "docs/superpowers/plans/2026-08-17-register-autowiring.md "
                "for the pattern used to replicate wpulse-style behavior "
                "with a plain 'w' field plus a core-side edge detector."
            )
        for field in register.fields:
            mappings.append(
                FieldMapping(
                    register_name=register.name,
                    field_name=field.name,
                    field_type=type(field),
                    width=field.width,
                    direction=direction,
                    port_name=f"{field.name}{suffix}",
                    needs_cast=isinstance(field, BitVector),
                )
            )
    return mappings


def resolve_port_mappings(mappings: list[FieldMapping], core_ports: dict[str, Port]) -> None:
    """Verify every field maps to an existing core port with the matching direction,
    and that no two fields target the same core port. Raises ValueError listing
    every problem found, not just the first."""
    errors = []

    port_name_owners: dict[str, list[FieldMapping]] = {}
    for mapping in mappings:
        port_name_owners.setdefault(mapping.port_name, []).append(mapping)
    for port_name, owners in port_name_owners.items():
        if len(owners) > 1:
            fields = ", ".join(f"'{m.register_name}.{m.field_name}'" for m in owners)
            errors.append(
                f"core port '{port_name}' is targeted by multiple register fields "
                f"({fields}) -- register field leaf names must be unique across "
                "the whole register map when auto-wiring a single core"
            )

    for mapping in mappings:
        port = core_ports.get(mapping.port_name)
        if port is None:
            errors.append(
                f"register field '{mapping.register_name}.{mapping.field_name}' "
                f"expects a core port named '{mapping.port_name}', but no such "
                "port exists"
            )
            continue
        expected_direction = "in" if mapping.direction == "down" else "out"
        actual_direction = "in" if port.direction in ("in", "input") else "out"
        if actual_direction != expected_direction:
            errors.append(
                f"core port '{mapping.port_name}' has direction "
                f"'{port.direction}', but register field "
                f"'{mapping.register_name}.{mapping.field_name}' needs "
                f"direction '{expected_direction}'"
            )
    if errors:
        raise ValueError(
            "Register field <-> core port mismatch:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )


def build_passthrough_mappings(
    core_ports: dict[str, Port],
    field_mappings: list[FieldMapping],
    top_ports: dict[str, Port],
) -> dict[str, str]:
    """For core ports not covered by any register field (e.g. clk, rst_n),
    connect them to an identically-named port on <<NAME>>_top."""
    covered = {m.port_name for m in field_mappings}
    passthrough: dict[str, str] = {}
    errors = []
    for name in core_ports:
        if name in covered:
            continue
        if name not in top_ports:
            errors.append(
                f"core port '{name}' is not a register-derived port and has "
                "no matching port on <<NAME>>_top to pass through"
            )
            continue
        passthrough[name] = name
    if errors:
        raise ValueError(
            "Unmapped core port(s):\n" + "\n".join(f"  - {e}" for e in errors)
        )
    return passthrough

def rewrite_marker_region(
    file_path: Path, begin_marker: str, end_marker: str, new_content: str
) -> None:
    """Replace the text strictly between a BEGIN/END marker comment pair.
    The markers themselves are preserved and left in place."""
    text = file_path.read_text()
    pattern = re.compile(re.escape(begin_marker) + r".*?" + re.escape(end_marker), re.DOTALL)
    if not pattern.search(text):
        raise ValueError(
            f"Could not find marker region '{begin_marker}' ... "
            f"'{end_marker}' in {file_path}. Add the marker comment pair "
            "before running `make regs`."
        )
    replacement = f"{begin_marker}\n{new_content}\n    {end_marker}"
    new_text = pattern.sub(lambda _match: replacement, text, count=1)
    file_path.write_text(new_text)


def render_vhdl_signals_block(field_mappings: list[FieldMapping]) -> str:
    """Bridging signal declarations for 'up' BitVector fields."""
    lines = [
        f"    signal {m.field_name} : std_logic_vector({m.width} - 1 downto 0);"
        for m in field_mappings
        if m.direction == "up" and m.needs_cast
    ]
    return "\n".join(lines)


def render_vhdl_wiring_block(
    name: str, field_mappings: list[FieldMapping], passthrough: dict[str, str]
) -> str:
    # 'up' (output-port) BitVector fields need an intermediate signal --
    # GHDL rejects both std_logic_vector(...) and unsigned(...) as inline
    # output-port conversions (verified empirically). 'down' (input-port)
    # BitVector fields don't have this restriction: VHDL allows an
    # arbitrary expression as an input-port actual, so std_logic_vector(...)
    # works inline there (also verified empirically) -- no bridging signal
    # needed for that direction.
    bridge_assignments = [
        f"    regs_up.{m.register_name}.{m.field_name} <= unsigned({m.field_name});"
        for m in field_mappings
        if m.direction == "up" and m.needs_cast
    ]

    port_lines = [f"            {formal} => {actual}" for formal, actual in passthrough.items()]
    for m in field_mappings:
        record = "regs_down" if m.direction == "down" else "regs_up"
        field_ref = f"{record}.{m.register_name}.{m.field_name}"
        if m.direction == "up" and m.needs_cast:
            actual = m.field_name  # connects to the bridging signal instead
        elif m.direction == "down" and m.needs_cast:
            actual = f"std_logic_vector({field_ref})"  # inline cast, input port
        else:
            actual = field_ref
        port_lines.append(f"            {m.port_name} => {actual}")

    instance = [
        f"    u_core : entity work.{name}_core",
        "        port map (",
        ",\n".join(port_lines),
        "        );",
    ]

    return "\n".join(bridge_assignments + ([""] if bridge_assignments else []) + instance)


def render_sv_wiring_block(
    name: str, field_mappings: list[FieldMapping], passthrough: dict[str, str]
) -> str:
    port_lines = [f"        .{formal}({actual})" for formal, actual in passthrough.items()]
    for m in field_mappings:
        if m.direction == "down":
            actual = f"hwif_out.{m.register_name}.{m.field_name}.value"
        else:
            actual = f"hwif_in.{m.register_name}.{m.field_name}.next"
        port_lines.append(f"        .{m.port_name}({actual})")

    return "\n".join(
        [
            f"    {name}_core u_core (",
            ",\n".join(port_lines),
            "    );",
        ]
    )


def generate_sv(register_list, output_folder: Path) -> None:
    """Generate the SystemVerilog AXI-Lite register file and its types package.
    Uses flatten_axi_lite=True so the bus side is discrete signals (s_axil_*),
    not a bundled SV interface -- keeps the bus-side wiring convention close
    to this project's existing hand-written SV top and avoids depending on
    an external interface definition.
    """
    SystemVerilogAxiLiteGenerator(register_list=register_list, output_folder=output_folder).create(
        flatten_axi_lite=True
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
REGS_DIR  = REPO_ROOT / "regs"
GEN_VHDL  = REPO_ROOT / "out" / "regs" / "vhdl"
GEN_SV    = REPO_ROOT / "out" / "regs" / "sv"
GEN_C     = REPO_ROOT / "out" / "regs" / "c"
GEN_HTML  = REPO_ROOT / "out" / "regs" / "html"


def detect_language(repo_root: Path) -> str:
    """Return "vhdl" or "sv" based on which core source file exists.
    Checks the flat post-`make init` layout (src/*_core.<ext>) first, then
    falls back to the pre-init per-language layout (src/vhdl/, src/sv/),
    preferring vhdl when both exist there -- matching this generator's
    historical VHDL-default behavior from before language auto-detection
    existed (it always ran the VHDL generators unconditionally)."""
    src_dir = repo_root / "src"
    if list(src_dir.glob("*_core.vhd")):
        return "vhdl"
    if list(src_dir.glob("*_core.sv")):
        return "sv"
    if list((src_dir / "vhdl").glob("*_core.vhd")):
        return "vhdl"
    if list((src_dir / "sv").glob("*_core.sv")):
        return "sv"
    raise ValueError(
        f"No *_core.vhd or *_core.sv found under {src_dir} -- run `make init` first."
    )


def _core_src_dir(repo_root: Path, language: str) -> Path:
    """Return the directory containing <name>_core/<name>_top for the given
    language -- flat src/ post-`make init`, or src/vhdl//src/sv/ pre-init."""
    src_dir = repo_root / "src"
    ext = "vhd" if language == "vhdl" else "sv"
    if list(src_dir.glob(f"*_core.{ext}")):
        return src_dir
    nested = src_dir / language
    if list(nested.glob(f"*_core.{ext}")):
        return nested
    raise ValueError(f"No *_core.{ext} found under {src_dir} or {nested}")


def _flat_core_and_top_exist(repo_root: Path, name: str, language: str) -> bool:
    """True only when the flat, post-`make init` src/ layout contains both
    <name>_core.<ext> and <name>_top.<ext> for this specific register list.
    Auto-wiring must never run against anything else: pre-init, the
    pre-init nested src/vhdl/, src/sv/ layout has the TOML-derived name as
    a template placeholder (e.g. "NAME"), and writing that literal name
    into <name>_top would corrupt the <<NAME>> token in a way `make init`
    cannot repair. Post-init, a second regs/*.toml with no matching
    <name>_core/<name>_top pair should be skipped, not crash.
    """
    ext = "vhd" if language == "vhdl" else "sv"
    src_dir = repo_root / "src"
    return (src_dir / f"{name}_core.{ext}").is_file() and (src_dir / f"{name}_top.{ext}").is_file()


def autowire_top(name: str, language: str, register_list, repo_root: Path) -> None:
    """Regenerate the marker-delimited register-wiring region(s) in <name>_top."""
    src_dir = _core_src_dir(repo_root, language)
    ext = "vhd" if language == "vhdl" else "sv"
    core_file = src_dir / f"{name}_core.{ext}"
    top_file = src_dir / f"{name}_top.{ext}"

    parse_ports = parse_vhdl_ports if language == "vhdl" else parse_sv_ports
    core_ports = parse_ports(core_file)
    top_ports = parse_ports(top_file)

    field_mappings = build_field_mappings(register_list)
    resolve_port_mappings(field_mappings, core_ports)
    passthrough = build_passthrough_mappings(core_ports, field_mappings, top_ports)

    if language == "vhdl":
        rewrite_marker_region(
            top_file,
            "-- BEGIN AUTOGEN REGISTER SIGNALS",
            "-- END AUTOGEN REGISTER SIGNALS",
            render_vhdl_signals_block(field_mappings),
        )
        rewrite_marker_region(
            top_file,
            "-- BEGIN AUTOGEN REGISTERS",
            "-- END AUTOGEN REGISTERS",
            render_vhdl_wiring_block(name, field_mappings, passthrough),
        )
    else:
        rewrite_marker_region(
            top_file,
            "// BEGIN AUTOGEN REGISTERS",
            "// END AUTOGEN REGISTERS",
            render_sv_wiring_block(name, field_mappings, passthrough),
        )
    print(f"  Auto-wired {top_file.relative_to(repo_root)}")


def generate_from_toml(toml_path: Path) -> None:
    """Generate all outputs for a single TOML register definition file."""
    # Derive the register list name from the TOML stem, stripping the
    # trailing '_regs' file-naming convention (regs/<name>_regs.toml) so the
    # register list itself is named '<name>' — hdl_registers' own generators
    # each append their own suffix (_regs_pkg.vhd, _regs.h, _regs.html, ...),
    # so keeping '_regs' in the list name would double it up.
    name = toml_path.stem.removesuffix("_regs")
    print(f"  Generating registers for: {name}")

    register_list = from_toml(name=name, toml_file=toml_path)

    language = detect_language(REPO_ROOT)
    if language == "vhdl":
        VhdlRegisterPackageGenerator(register_list=register_list, output_folder=GEN_VHDL).create()
        VhdlRecordPackageGenerator(register_list=register_list, output_folder=GEN_VHDL).create()
        VhdlAxiLiteWrapperGenerator(register_list=register_list, output_folder=GEN_VHDL).create()
    else:
        generate_sv(register_list, GEN_SV)

    CHeaderGenerator(register_list=register_list, output_folder=GEN_C).create()
    HtmlPageGenerator(register_list=register_list, output_folder=GEN_HTML).create()

    if _flat_core_and_top_exist(REPO_ROOT, name, language):
        autowire_top(name=name, language=language, register_list=register_list, repo_root=REPO_ROOT)
    else:
        print(
            f"  Skipping _top auto-wiring for '{name}': no flat src/{name}_core.{{vhd,sv}} "
            f"+ src/{name}_top.{{vhd,sv}} pair found (run \`make init\` first, or this "
            "TOML has no matching core/top pair)."
        )


def main() -> None:
    for d in (GEN_VHDL, GEN_SV, GEN_C, GEN_HTML):
        d.mkdir(parents=True, exist_ok=True)

    toml_files = sorted(REGS_DIR.glob("*.toml"))
    if not toml_files:
        print(f"WARNING: No TOML files found in {REGS_DIR}")
        return

    for toml_path in toml_files:
        generate_from_toml(toml_path)

    print("Register generation complete.")
    print(f"  VHDL  → {GEN_VHDL}")
    print(f"  C     → {GEN_C}")
    print(f"  HTML  → {GEN_HTML}")


if __name__ == "__main__":
    try:
        main()
    except ValueError as e:
        print(f"\n  ERROR: {e}\n")
        raise SystemExit(1)
