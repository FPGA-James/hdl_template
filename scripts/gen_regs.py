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
