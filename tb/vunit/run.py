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

import subprocess
from pathlib import Path
from vunit import VUnit

# Repository root (two levels up from this file: tb/vunit/run.py → repo root)
ROOT = Path(__file__).resolve().parents[2]

vu = VUnit.from_argv()
vu.add_vhdl_builtins()
# Needed for vunit_lib.bus_master_pkg / com_types_pkg, used by the generated
# read/write package (and transitively by register_operations_pkg) to drive
# the axi_lite_master BFM -- not pulled in by add_vhdl_builtins() alone.
vu.add_verification_components()

# ── hdl-modules dependency (AXI-Lite types, register file, and the
# axi_lite_master BFM that drives <<NAME>>_top's AXI-Lite port) ─────────────
HDL_MODULES = Path(
    subprocess.run(
        ["bender", "path", "hdl_modules"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
)

axi_lite_lib = vu.add_library("axi_lite")
axi_lite_lib.add_source_files(HDL_MODULES / "modules" / "axi_lite" / "src" / "axi_lite_pkg.vhd")

# math: needed transitively by common.addr_pkg (used by register_file's
# register_operations_pkg, in turn pulled in by the generated read/write
# package). Not needed by lint-vhdl/synth, so it isn't already wired in
# elsewhere.
math_lib = vu.add_library("math")
math_lib.add_source_files(HDL_MODULES / "modules" / "math" / "src" / "math_pkg.vhd")

# common: needed transitively both by the axi_lite_master BFM's internal
# axi_stream_protocol_checker instances, and by register_file's
# register_operations_pkg (via common.addr_pkg.addr_t) -- neither needed by
# lint-vhdl/synth, which never use the BFM or the legacy read/write helpers,
# so this library isn't already wired in elsewhere.
common_lib = vu.add_library("common")
common_lib.add_source_files(HDL_MODULES / "modules" / "common" / "src" / "types_pkg.vhd")
common_lib.add_source_files(HDL_MODULES / "modules" / "common" / "src" / "common_pkg.vhd")
common_lib.add_source_files(HDL_MODULES / "modules" / "common" / "src" / "addr_pkg.vhd")
common_lib.add_source_files(
    HDL_MODULES / "modules" / "common" / "src" / "axi_stream_protocol_checker.vhd"
)

register_file_lib = vu.add_library("register_file")
register_file_lib.add_source_files(
    HDL_MODULES / "modules" / "register_file" / "src" / "register_file_pkg.vhd"
)
register_file_lib.add_source_files(
    HDL_MODULES / "modules" / "register_file" / "src" / "axi_lite_register_file.vhd"
)
register_file_lib.add_source_files(
    HDL_MODULES / "modules" / "register_file" / "sim" / "register_operations_pkg.vhd"
)

bfm_lib = vu.add_library("bfm")
bfm_lib.add_source_files(HDL_MODULES / "modules" / "bfm" / "sim" / "axi_lite_master.vhd")

# ── RTL library ──────────────────────────────────────────────────────────────
rtl_lib = vu.add_library("rtl_lib")
rtl_lib.add_source_files(ROOT / "src" / "<<NAME>>_pkg.vhd")
rtl_lib.add_source_files(ROOT / "src" / "<<NAME>>_core.vhd")
rtl_lib.add_source_files(ROOT / "src" / "<<NAME>>_top.vhd")

# ── Generated register files (produced by `make regs`) ──────────────────────
gen_dir = ROOT / "out" / "regs" / "vhdl"
rtl_lib.add_source_files(gen_dir / "<<NAME>>_regs_pkg.vhd")
rtl_lib.add_source_files(gen_dir / "<<NAME>>_register_record_pkg.vhd")
rtl_lib.add_source_files(gen_dir / "<<NAME>>_register_file_axi_lite.vhd")
rtl_lib.add_source_files(gen_dir / "<<NAME>>_register_read_write_pkg.vhd")

# ── Testbench library ─────────────────────────────────────────────────────────
tb_lib = vu.add_library("tb_lib")
tb_lib.add_source_files(ROOT / "tb" / "vunit" / "vhdl" / "<<NAME>>_tb.vhd")

vu.main()
