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
    """Verify every field maps to an existing core port with the matching direction.
    Raises ValueError listing every problem found, not just the first."""
    errors = []
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

REPO_ROOT = Path(__file__).resolve().parents[1]
REGS_DIR  = REPO_ROOT / "regs"
GEN_VHDL  = REPO_ROOT / "out" / "regs" / "vhdl"
GEN_C     = REPO_ROOT / "out" / "regs" / "c"
GEN_HTML  = REPO_ROOT / "out" / "regs" / "html"


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

    # VHDL: register address/field constants package (<name>_regs_pkg.vhd)
    VhdlRegisterPackageGenerator(
        register_list=register_list, output_folder=GEN_VHDL
    ).create()

    # VHDL: natively-typed record package (<name>_register_record_pkg.vhd)
    VhdlRecordPackageGenerator(
        register_list=register_list, output_folder=GEN_VHDL
    ).create()

    # VHDL: AXI-Lite register file wrapper (<name>_register_file_axi_lite.vhd)
    # This is the entity instantiated in <<NAME>>_top as u_regs.
    VhdlAxiLiteWrapperGenerator(
        register_list=register_list, output_folder=GEN_VHDL
    ).create()

    # C: register address/field header (<name>_regs.h)
    CHeaderGenerator(
        register_list=register_list, output_folder=GEN_C
    ).create()

    # HTML: register documentation page (<name>_regs.html)
    HtmlPageGenerator(
        register_list=register_list, output_folder=GEN_HTML
    ).create()


def main() -> None:
    for d in (GEN_VHDL, GEN_C, GEN_HTML):
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
    main()
