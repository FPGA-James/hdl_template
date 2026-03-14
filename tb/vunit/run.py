#!/usr/bin/env python3
"""VUnit test runner for the <<NAME>> design.

Run with GHDL (set by the Makefile via VUNIT_SIMULATOR):
    make sim FRAMEWORK=vunit

Or directly:
    VUNIT_SIMULATOR=ghdl python tb/vunit/run.py
    VUNIT_SIMULATOR=ghdl python tb/vunit/run.py -v --no-color   # verbose
    VUNIT_SIMULATOR=ghdl python tb/vunit/run.py --list           # list tests
    VUNIT_SIMULATOR=ghdl python tb/vunit/run.py -g               # GUI mode
"""

from pathlib import Path
from vunit import VUnit

# Repository root (two levels up from this file: tb/vunit/run.py → repo root)
ROOT = Path(__file__).resolve().parents[2]

vu = VUnit.from_argv(compile_builtins=False)
vu.add_vhdl_builtins()

# ── RTL library ──────────────────────────────────────────────────────────────
rtl_lib = vu.add_library("work")

rtl_lib.add_source_files(ROOT / "src" / "vhdl" / "NAME_pkg.vhd")
rtl_lib.add_source_files(ROOT / "src" / "vhdl" / "NAME_core.vhd")

# Generated register packages (run `make regs` first).
# NAME_top.vhd is not included here because the testbench targets NAME_core
# directly; the AXI-Lite register file requires the hdl-modules library.
for gen_file in sorted((ROOT / "gen" / "vhdl").glob("*.vhd")):
    rtl_lib.add_source_files(gen_file)

# ── Testbench library ─────────────────────────────────────────────────────────
tb_lib = vu.add_library("tb_lib")
tb_lib.add_source_files(ROOT / "tb" / "vunit" / "vhdl" / "NAME_tb.vhd")

vu.main()
