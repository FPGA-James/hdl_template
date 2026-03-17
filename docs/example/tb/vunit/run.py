#!/usr/bin/env python3
"""VUnit test runner for the uart design.

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

_out = str(Path(__file__).resolve().parents[2] / "out" / "vunit")
vu = VUnit.from_argv(argv=["-o", _out] + __import__("sys").argv[1:],
                     compile_builtins=False)
vu.add_vhdl_builtins()

# ── RTL library ──────────────────────────────────────────────────────────────
rtl_lib = vu.add_library("uart_lib")

rtl_lib.add_source_files(ROOT / "src" / "vhdl" / "uart_pkg.vhd")
rtl_lib.add_source_files(ROOT / "src" / "vhdl" / "uart_tx.vhd")
rtl_lib.add_source_files(ROOT / "src" / "vhdl" / "uart_rx.vhd")
rtl_lib.add_source_files(ROOT / "src" / "vhdl" / "uart_core.vhd")

# uart_top.vhd is not included here — the testbench targets uart_core directly.
# uart_top requires the generated register packages and hdl-modules library.

# ── Testbench (same library as RTL so 'library work' resolves correctly) ────
rtl_lib.add_source_files(ROOT / "tb" / "vunit" / "vhdl" / "uart_tb.vhd")

vu.main()
