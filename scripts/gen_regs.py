#!/usr/bin/env python3
"""Register generation script for the HDL template.

Parses all TOML register definitions in regs/ and generates, for the
detected project language (VHDL or SystemVerilog):
  - VHDL: register constants package, typed record package, and AXI-Lite
    register file wrapper                  → out/regs/vhdl/
  - SV: AXI-Lite register file module and types package (via PeakRDL-
    regblock, post-processed for OSS Yosys synthesizability)
                                            → out/regs/sv/
  - C header file                          → out/regs/c/
  - HTML register documentation            → out/regs/html/ (linked by Sphinx)

Also auto-wires each register field to a matching `<name>_core` port,
rewriting the marker-delimited region(s) of `<name>_top` -- see
`autowire_top` below.

Run via: make regs
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from hdl_registers.parser.toml import from_toml
from hdl_registers.register_array import RegisterArray
from hdl_registers.generator.vhdl.register_package import VhdlRegisterPackageGenerator
from hdl_registers.generator.vhdl.record_package import VhdlRecordPackageGenerator
from hdl_registers.generator.vhdl.axi_lite.wrapper import VhdlAxiLiteWrapperGenerator
from hdl_registers.generator.vhdl.simulation.read_write_package import (
    VhdlSimulationReadWritePackageGenerator,
)
from hdl_registers.generator.systemverilog.axi_lite.register_file import (
    SystemVerilogAxiLiteGenerator,
)
from hdl_registers.generator.c.header import CHeaderGenerator
from hdl_registers.generator.html.page import HtmlPageGenerator
from hdl_registers.field.bit_vector import BitVector


# =============================================================================
# Port parsing
# =============================================================================


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
            # Check if this is an interface port (no input/output keyword).
            # Interface ports have patterns like "axil_if.slave s_axil" with
            # explicit modport.port syntax (required by Yosys). Captured
            # below with direction="interface" rather than skipped -- see
            # the comment on that branch for why.
            # The dot is mandatory to distinguish from missing input/output keywords.
            interface_match = re.match(r"(\w+)\.(\w+)\s+(\w+)$", entry)
            if interface_match:
                # Interface ports (e.g. "axis_if.slave s_axis") are never
                # register-derived, so they never appear in field_mappings and
                # never reach resolve_port_mappings' direction check -- but
                # they DO need to reach build_passthrough_mappings, which
                # connects any core port not covered by a register field to
                # an identically-named _top port purely by name (no direction
                # check there either). Capturing them here (direction=
                # "interface") instead of skipping them is what makes e.g.
                # <<NAME>>_core's s_axis auto-connect to <<NAME>>_top's s_axis, the same
                # way clk already auto-connects to clk.
                iface_type, modport, iface_name = interface_match.groups()
                ports[iface_name] = Port(
                    name=iface_name, direction="interface", type_str=f"{iface_type}.{modport}"
                )
                continue
            raise ValueError(f"Could not parse port declaration: {entry!r} in {core_file}")
        direction, type_str, name = port_match.groups()
        ports[name] = Port(name=name, direction=direction, type_str=type_str.strip())
    return ports


# =============================================================================
# Field-to-port mapping
# =============================================================================

# Registers that are read/write over the bus like any other, but
# intentionally get NO matching <name>_core port -- auto-wiring skips them
# entirely (build_field_mappings never emits a FieldMapping for them, so
# resolve_port_mappings never demands a core port either). Two distinct
# reasons a register ends up here:
#
# FIXED_VALUE_REGISTERS: 'r'-mode, no hardware behind it at all -- <name>_top
#   drives its hwif_in field directly with a compile-time constant (see
#   build_fixed_value_lines below) instead of instantiating a core port.
#   Typical use: module_id/version, which never change at runtime.
# NO_CORE_WIRING_REGISTERS: writable (w/r_w/wpulse), but the value software
#   writes isn't consumed by anything (yet). Left unconnected: an r_w
#   register's read side loops back the last-written value inside the
#   generated register file itself (hardware_has_up=False for r_w -- see
#   hdl_registers.register_modes), so no core port is needed even for the
#   read-back to work. Typical use: a pure scratch register to verify bus
#   read/write access.
# Both tables are empty by default: no register name is special until your project adds it.
# Example: FIXED_VALUE_REGISTERS = {"module_id": 0x41424344, "version": 0x00010000}
FIXED_VALUE_REGISTERS: dict[str, int] = {}
# Example: NO_CORE_WIRING_REGISTERS = {"scratch"}
NO_CORE_WIRING_REGISTERS: set[str] = set()


@dataclass
class FieldMapping:
    """A single register field, resolved to the core port it drives/receives."""

    register_name: str
    field_name: str
    width: int
    direction: str  # "down" (host writes, core input) or "up" (host reads, core output)
    port_name: str
    needs_cast: bool  # VHDL only: True for BitVector fields (record type is `unsigned`)


def build_field_mappings(register_list) -> list[FieldMapping]:
    """Walk the register list and compute each field's expected core port name,
    direction, and whether a VHDL type cast is needed to reach that port.
    Skips FIXED_VALUE_REGISTERS/NO_CORE_WIRING_REGISTERS entirely -- see
    their docstring above."""
    mappings: list[FieldMapping] = []
    for register in register_list.register_objects:
        if register.name in FIXED_VALUE_REGISTERS or register.name in NO_CORE_WIRING_REGISTERS:
            continue
        mode = register.mode.shorthand
        if mode in ("w", "r_w", "wpulse"):
            direction, suffix = "down", "_i"
        elif mode == "r":
            direction, suffix = "up", "_o"
        else:
            raise ValueError(
                f"Register '{register.name}' uses mode '{mode}', which "
                "register auto-wiring does not support (only r, w, r_w, "
                "wpulse — this applies to VHDL and SystemVerilog projects "
                "alike, since the wiring layer has no naming convention "
                "for other modes yet). To replicate wpulse-style behavior "
                "without it, use a plain 'w' field plus a core-side edge "
                "detector instead (see the reset_count field in the "
                "example project's register map and _core RTL for the "
                "pattern)."
            )
        for field in register.fields:
            mappings.append(
                FieldMapping(
                    register_name=register.name,
                    field_name=field.name,
                    width=field.width,
                    direction=direction,
                    port_name=f"{field.name}{suffix}",
                    needs_cast=isinstance(field, BitVector),
                )
            )
    return mappings


def build_fixed_value_lines(register_list, language: str) -> list[str]:
    """Emit the line that drives each present FIXED_VALUE_REGISTERS entry's
    'r'-mode field with its compile-time constant, bypassing <name>_core
    entirely. A register named in FIXED_VALUE_REGISTERS but absent from this
    project's register list is silently skipped (lets the dict be a fixed
    superset shared across projects). Only single-field 'r'-mode registers
    are supported -- the only shape FIXED_VALUE_REGISTERS is meant for."""
    by_name = {r.name: r for r in register_list.register_objects if not isinstance(r, RegisterArray)}
    lines = []
    for reg_name, value in FIXED_VALUE_REGISTERS.items():
        register = by_name.get(reg_name)
        if register is None:
            continue
        if register.mode.shorthand != "r":
            raise ValueError(
                f"FIXED_VALUE_REGISTERS['{reg_name}'] must be mode 'r' (hardware-driven, "
                f"no software write), got mode '{register.mode.shorthand}'"
            )
        if len(register.fields) != 1:
            raise ValueError(
                f"FIXED_VALUE_REGISTERS['{reg_name}'] must have exactly one field, "
                f"got {len(register.fields)}"
            )
        field = register.fields[0]
        width = field.width
        if language == "vhdl":
            # regs_up.<reg>.<field> is typed `unsigned` (see render_vhdl_wiring_block's
            # bridging comment) -- to_unsigned needs a plain (non-hex-literal) integer.
            lines.append(f"    regs_up.{reg_name}.{field.name} <= to_unsigned(16#{value:x}#, {width});")
        else:
            nibbles = (width + 3) // 4
            lines.append(f"    assign hwif_in.{reg_name}.{field.name}.next = {width}'h{value:0{nibbles}x};")
    return lines


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
    connect them to an identically-named port on the project's _top module."""
    covered = {m.port_name for m in field_mappings}
    passthrough: dict[str, str] = {}
    errors = []
    for name in core_ports:
        if name in covered:
            continue
        if name not in top_ports:
            errors.append(
                f"core port '{name}' is not a register-derived port and has "
                "no matching port on the project's _top module to pass through"
            )
            continue
        passthrough[name] = name
    if errors:
        raise ValueError(
            "Unmapped core port(s):\n" + "\n".join(f"  - {e}" for e in errors)
        )
    return passthrough


# =============================================================================
# Marker-region rewrite and rendering
# =============================================================================


def rewrite_marker_region(
    file_path: Path, begin_marker: str, end_marker: str, new_content: str
) -> None:
    """Replace the text strictly between a BEGIN/END marker comment pair.
    The markers themselves are preserved and left in place. The END
    marker's original indentation is preserved too -- captured from the
    match rather than assumed, so this works regardless of how the marker
    comment happens to be indented in the source file."""
    text = file_path.read_text()
    pattern = re.compile(
        re.escape(begin_marker) + r".*?([ \t]*)" + re.escape(end_marker), re.DOTALL
    )
    match = pattern.search(text)
    if not match:
        raise ValueError(
            f"Could not find marker region '{begin_marker}' ... "
            f"'{end_marker}' in {file_path}. Add the marker comment pair "
            "before running `make regs`."
        )
    end_indent = match.group(1)
    replacement = f"{begin_marker}\n{new_content}\n{end_indent}{end_marker}"
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
    name: str,
    field_mappings: list[FieldMapping],
    passthrough: dict[str, str],
    fixed_value_lines: list[str] | None = None,
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

    fixed_value_lines = fixed_value_lines or []
    return "\n".join(
        bridge_assignments
        + ([""] if bridge_assignments else [])
        + instance
        + ([""] + fixed_value_lines if fixed_value_lines else [])
    )


def render_sv_wiring_block(
    name: str,
    field_mappings: list[FieldMapping],
    passthrough: dict[str, str],
    fixed_value_lines: list[str] | None = None,
) -> str:
    port_lines = [f"        .{formal}({actual})" for formal, actual in passthrough.items()]
    for m in field_mappings:
        if m.direction == "down":
            actual = f"hwif_out.{m.register_name}.{m.field_name}.value"
        else:
            actual = f"hwif_in.{m.register_name}.{m.field_name}.next"
        port_lines.append(f"        .{m.port_name}({actual})")

    instance = [
        f"    {name}_core u_core (",
        ",\n".join(port_lines),
        "    );",
    ]
    fixed_value_lines = fixed_value_lines or []
    return "\n".join(instance + ([""] + fixed_value_lines if fixed_value_lines else []))


# =============================================================================
# SystemVerilog register-file generation
# =============================================================================


def _make_sv_synthesizable(text: str) -> str:
    """Rewrite PeakRDL-regblock's generated SystemVerilog so free/OSS Yosys's
    `read_verilog -sv` frontend can synthesize it. Two independent gaps,
    verified empirically against this project's real generated register
    file with a full `synth` run (zero CHECK-pass problems, real gates
    produced):

    1. Every `struct { ... }` (the top-level typedefs AND their nested
       anonymous members -- hwif_in/hwif_out are deeply nested) is
       unpacked; Yosys only supports packed structs ("ERROR: Only PACKED
       supported at this time"). Packing every level is required, not
       just the outermost: SV forbids an unpacked member inside a packed
       struct, and every leaf here is already a plain `logic`/`logic[N:0]`
       (no dynamic arrays or queues), so packing the whole hierarchy is
       safe. Already-packed structs (`struct packed {`, used for external
       sub-word registers) are left alone -- the regex only matches
       `struct {` with nothing between `struct` and `{`.
    2. `automatic` local variables inside `always_comb` blocks aren't
       parsed at all ("syntax error, unexpected TOK_AUTOMATIC"). Stripping
       the keyword is safe here: these blocks never recurse and never run
       concurrently with themselves, so automatic vs. implicit-static
       storage has no behavioral difference.

    Verified inert for existing consumers too: Verilator (lint-sv,
    sim-cocotb-verilator, sim-native) accepts the rewritten file with the
    same pre-existing, unrelated warnings as the original.
    """
    text = re.sub(r"\bstruct \{", "struct packed {", text)
    text = re.sub(r"\bautomatic\s+", "", text)
    return text


_SV_DECODE_PASS_DOWN = """    // Pass down signals to next stage
    assign decoded_addr = cpuif_addr;
    assign decoded_req = cpuif_req_masked;
    assign decoded_req_is_wr = cpuif_req_is_wr;
    assign decoded_wr_data = cpuif_wr_data;
    assign decoded_wr_biten = cpuif_wr_biten;
"""

_SV_DECODE_REGISTERED = """    // Pass down signals to next stage, registered (scripts/gen_regs.py,
    // _register_sv_decode): one cycle of latency for timing.
    always_ff @(posedge clk) begin
        if(rst) begin
            decoded_reg_strb <= '0;
            decoded_req <= '0;
        end else begin
            decoded_reg_strb <= decoded_reg_strb_c;
            decoded_req <= cpuif_req_masked;
        end
        decoded_addr <= cpuif_addr;
        decoded_req_is_wr <= cpuif_req_is_wr;
        decoded_wr_data <= cpuif_wr_data;
        decoded_wr_biten <= cpuif_wr_biten;
    end
"""


def _register_sv_decode(text: str) -> str:
    """Put a register between PeakRDL-regblock's address decode and its field logic.
    The unregistered path (CPU-interface request, then address decode, then each field's
    load enable, which fans out to every bit of the field) is the longest in the design at
    high clock rates. Read and write requests both pass through the register, so they
    stay in order and keep equal latency (regblock's "latencies are balanced, stalls not
    required" still holds). Each response comes one cycle later; the in-flight limit
    already counts requests from acceptance, so the two-entry response buffer cannot
    overflow. Raises if regblock's output no longer has the expected shape.
    """
    decl = "    decoded_reg_strb_t decoded_reg_strb;\n"
    if decl not in text or _SV_DECODE_PASS_DOWN not in text:
        raise ValueError("unexpected PeakRDL-regblock output: decode stage not found")
    text = text.replace(decl, "    decoded_reg_strb_t decoded_reg_strb_c, decoded_reg_strb;\n")
    text, n = re.subn(r"^(\s*)decoded_reg_strb\.(\w+) = ", r"\1decoded_reg_strb_c.\2 = ", text, flags=re.M)
    if n == 0:
        raise ValueError("unexpected PeakRDL-regblock output: no decoded_reg_strb assignments")
    return text.replace(_SV_DECODE_PASS_DOWN, _SV_DECODE_REGISTERED)


def render_sv_address_constants(register_list, addr_width: int | None = None) -> str:
    """Generate a small SV package with one localparam per plain register's
    byte address (4 * the register's real index within the register list)
    -- the same computation the VHDL path's generated read/write package
    uses internally. Verified: generated for this project's real register
    map, compiled and ran cleanly under Verilator (Icarus cannot parse the interface-based top).

    Uses each register's own `.index` attribute, not its position in
    `register_objects` (via `enumerate()`): a `RegisterArray` earlier in
    the list consumes multiple indices (one per array element) but is a
    single entry in `register_objects`, so positional enumeration silently
    produces wrong addresses for every plain register that follows one.
    `RegisterArray` entries themselves are skipped -- they have no single
    address of their own, and this template's register auto-wiring
    doesn't support arrays anyway (each field must resolve to one
    <name>_core port).

    Names are deliberately lowercase (demo_conf_addr, not DEMO_CONF_ADDR):
    <<NAME>> template substitution is a literal, case-preserving text
    replacement, so only lowercase-project-name-prefixed identifiers are
    reachable from a template testbench file written pre-init. This also
    matches <name>_regs_pkg.vhd's existing lowercase constant convention
    (demo_conf, demo_command, demo_status).

    `addr_width`, when given, adds `<name>_addr_width`: the bit width of the
    generated register file's address ports, for the top to slice an
    interface address down to (the register file's own constant is uppercase).
    """
    name = register_list.name
    lines = [f"package {name}_regs_addr_pkg;"]
    if addr_width is not None:
        lines.append(f"    localparam int unsigned {name}_addr_width = {addr_width};")
    for register in register_list.register_objects:
        if isinstance(register, RegisterArray):
            continue
        const_name = f"{name}_{register.name}_addr"
        lines.append(f"    localparam int unsigned {const_name} = 4 * {register.index};")
    lines.append("endpackage")
    return "\n".join(lines) + "\n"


def generate_sv(register_list, output_folder: Path) -> None:
    """Generate the SystemVerilog AXI-Lite register file and its types package.
    Uses flatten_axi_lite=True so the bus side is discrete signals (s_axil_*),
    not a bundled SV interface -- keeps the bus-side wiring convention close
    to this project's existing hand-written SV top and avoids depending on
    an external interface definition.

    Post-processes both generated files (see `_make_sv_synthesizable`) so
    the output is synthesizable by free/OSS Yosys, not just simulatable, and
    registers the register file's decode stage (see `_register_sv_decode`).
    """
    SystemVerilogAxiLiteGenerator(register_list=register_list, output_folder=output_folder).create(
        flatten_axi_lite=True
    )

    for filename in (
        f"{register_list.name}_register_file_axi_lite.sv",
        f"{register_list.name}_register_file_axi_lite_pkg.sv",
    ):
        generated_file = output_folder / filename
        text = _make_sv_synthesizable(generated_file.read_text())
        if filename.endswith("_axi_lite.sv"):
            text = _register_sv_decode(text)
        generated_file.write_text(text)

    reg_pkg = (output_folder / f"{register_list.name}_register_file_axi_lite_pkg.sv").read_text()
    addr_width = int(re.search(r"MIN_ADDR_WIDTH\s*=\s*(\d+)", reg_pkg).group(1))
    addr_pkg_file = output_folder / f"{register_list.name}_regs_addr_pkg.sv"
    addr_pkg_file.write_text(render_sv_address_constants(register_list, addr_width))


# =============================================================================
# Driver
# =============================================================================

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
    nested src/vhdl/, src/sv/ layout has the TOML-derived name as
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
    fixed_value_lines = build_fixed_value_lines(register_list, language)

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
            render_vhdl_wiring_block(name, field_mappings, passthrough, fixed_value_lines),
        )
    else:
        rewrite_marker_region(
            top_file,
            "// BEGIN AUTOGEN REGISTERS",
            "// END AUTOGEN REGISTERS",
            render_sv_wiring_block(name, field_mappings, passthrough, fixed_value_lines),
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
        VhdlSimulationReadWritePackageGenerator(register_list=register_list, output_folder=GEN_VHDL).create()
    else:
        generate_sv(register_list, GEN_SV)

    CHeaderGenerator(register_list=register_list, output_folder=GEN_C).create()
    HtmlPageGenerator(register_list=register_list, output_folder=GEN_HTML).create()

    if _flat_core_and_top_exist(REPO_ROOT, name, language):
        autowire_top(name=name, language=language, register_list=register_list, repo_root=REPO_ROOT)
    else:
        print(
            f"  Skipping _top auto-wiring for '{name}': no flat src/{name}_core.{{vhd,sv}} "
            f"+ src/{name}_top.{{vhd,sv}} pair found (run `make init` first, or this "
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
    if detect_language(REPO_ROOT) == "vhdl":
        print(f"  VHDL  → {GEN_VHDL}")
    else:
        print(f"  SV    → {GEN_SV}")
    print(f"  C     → {GEN_C}")
    print(f"  HTML  → {GEN_HTML}")


if __name__ == "__main__":
    try:
        main()
    except ValueError as e:
        print(f"\n  ERROR: {e}\n")
        raise SystemExit(1)
