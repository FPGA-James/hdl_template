"""Pytest entry-point for the cocotb testbench.

Discovered automatically by pytest (testpaths includes tb/cocotb).
Uses cocotb_tools.runner to compile the HDL once per session, then runs
each @cocotb.test() as an individual pytest item.

Environment overrides (defaults match the repo's standard GHDL+VHDL flow):
    SIM          ghdl | verilator | icarus   (default: ghdl)
    TOPLEVEL_HDL vhdl | sv                   (default: vhdl)

Run via make:
    make sim-cocotb                          # all tests, GHDL+VHDL
    make sim FRAMEWORK=cocotb SIM=verilator TOPLEVEL_HDL=sv

Or directly with pytest (OSS CAD Suite must be on PATH):
    pytest tb/cocotb/test_runner.py -v
    pytest tb/cocotb/test_runner.py -v -k test_tx_loopback
"""

import os
import sys
from pathlib import Path

import pytest
from cocotb_tools.runner import VHDL, get_runner

REPO_ROOT = Path(__file__).resolve().parents[2]

SIM = os.environ.get("SIM", "ghdl")
TOPLEVEL_HDL = os.environ.get("TOPLEVEL_HDL", "vhdl")

# When running pytest directly (not via make), OSS CAD Suite may not be on
# PATH yet.  Prepend it here so the simulator executables are found.
_oss = Path(os.environ.get("OSS_CAD_SUITE", Path.home() / "tools" / "oss-cad-suite"))
if _oss.is_dir():
    os.environ["PATH"] = f"{_oss/'bin'}:{_oss/'py3bin'}:{os.environ['PATH']}"
    os.environ.setdefault("GHDL_PREFIX", str(_oss / "lib" / "ghdl"))
    os.environ.setdefault(
        "VERILATOR_ROOT", str(_oss / "share" / "verilator")
    )
BUILD_DIR = REPO_ROOT / "out" / "cocotb"

VHDL_SOURCES = [
    REPO_ROOT / "src/vhdl/uart_pkg.vhd",
    REPO_ROOT / "src/vhdl/uart_tx.vhd",
    REPO_ROOT / "src/vhdl/uart_rx.vhd",
    REPO_ROOT / "src/vhdl/uart_core.vhd",
]

SV_SOURCES = [
    REPO_ROOT / "src/sv/uart_pkg.sv",
    REPO_ROOT / "src/sv/uart_core.sv",
]

COCOTB_TESTS = [
    "test_tx_loopback",
    "test_rx_byte",
    "test_tx_busy",
    "test_rx_frame_error",
]


@pytest.fixture(scope="session")
def built_runner():
    """Compile the HDL sources once and return the ready-to-test runner."""
    runner = get_runner(SIM)
    if TOPLEVEL_HDL == "vhdl":
        runner.build(
            sources=[VHDL(s) for s in VHDL_SOURCES],
            hdl_toplevel="uart_core",
            build_args=[VHDL("--std=08")],
            build_dir=BUILD_DIR,
        )
    else:
        runner.build(
            sources=SV_SOURCES,
            hdl_toplevel="uart_core",
            build_dir=BUILD_DIR,
        )
    return runner


# Make the cocotb test directory importable so test_uart.py is found.
sys.path.insert(0, str(Path(__file__).parent))


@pytest.mark.parametrize("test_name", COCOTB_TESTS)
def test_cocotb(built_runner, test_name):
    """Run a single cocotb test case inside the compiled simulation."""
    built_runner.test(
        test_module="test_uart",
        hdl_toplevel="uart_core",
        testcase=test_name,
        build_dir=BUILD_DIR,
        test_dir=BUILD_DIR,
    )
