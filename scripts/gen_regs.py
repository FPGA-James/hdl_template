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

from pathlib import Path

from hdl_registers.parser.toml import from_toml
from hdl_registers.generator.vhdl.register_package import VhdlRegisterPackageGenerator
from hdl_registers.generator.vhdl.record_package import VhdlRecordPackageGenerator
from hdl_registers.generator.vhdl.axi_lite.wrapper import VhdlAxiLiteWrapperGenerator
from hdl_registers.generator.c.header import CHeaderGenerator
from hdl_registers.generator.html.page import HtmlPageGenerator

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
