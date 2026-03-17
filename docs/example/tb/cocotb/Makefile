# cocotb simulation Makefile for uart_core.
#
# Called by the top-level Makefile via: make -C tb/cocotb SIM= TOPLEVEL= TOPLEVEL_HDL=
#
# Supported combinations:
#   SIM=ghdl       TOPLEVEL_HDL=vhdl  — VHDL via GHDL + VHPI
#   SIM=verilator  TOPLEVEL_HDL=sv    — SystemVerilog via Verilator + VPI
#   SIM=icarus     TOPLEVEL_HDL=sv    — SystemVerilog via Icarus Verilog + VPI
#
# The top-level for cocotb tests is uart_core (not _top), so the AXI-Lite
# register block is not involved and no hdl-modules dependency is needed.

# ── Configurable variables (passed in from top-level Makefile) ────────────────
SIM          ?= ghdl
TOPLEVEL     ?= uart_core
TOPLEVEL_HDL ?= vhdl
MODULE       ?= test_uart
REPO_ROOT    := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))../..)
SIM_BUILD    ?= $(REPO_ROOT)/out/cocotb

# Ensure the project venv's Python/cocotb takes precedence over any system
# or OSS CAD Suite Python so cocotb-config resolves to the correct version.
export PATH := $(REPO_ROOT)/.venv/bin:$(PATH)

# cocotb's libembed.so looks for libpython via LIBPYTHON_LOC first, then falls
# back to a hardcoded framework path.  Point it at the pyenv dylib so that the
# GPI layer can embed Python when Python was installed via pyenv rather than the
# official macOS Python.org installer.
export LIBPYTHON_LOC ?= $(shell $(REPO_ROOT)/.venv/bin/python3 -c "import sysconfig, os; print(os.path.join(sysconfig.get_config_var('LIBDIR'), sysconfig.get_config_var('LDLIBRARY')))" 2>/dev/null)

COCOTB_MAKEFILES := $(shell $(REPO_ROOT)/.venv/bin/cocotb-config --makefiles)

# ── Compatibility guard ────────────────────────────────────────────────────────
ifeq ($(TOPLEVEL_HDL),vhdl)
    ifeq ($(filter ghdl,$(SIM)),)
        $(error TOPLEVEL_HDL=vhdl requires SIM=ghdl, got SIM=$(SIM))
    endif
    TOPLEVEL_LANG   := vhdl
    VHDL_SOURCES    := \
      $(REPO_ROOT)/src/vhdl/uart_pkg.vhd \
      $(REPO_ROOT)/src/vhdl/uart_tx.vhd \
      $(REPO_ROOT)/src/vhdl/uart_rx.vhd \
      $(REPO_ROOT)/src/vhdl/uart_core.vhd
    VERILOG_SOURCES :=
    COMPILE_ARGS    += --std=08
else ifeq ($(TOPLEVEL_HDL),sv)
    ifeq ($(filter verilator icarus,$(SIM)),)
        $(error TOPLEVEL_HDL=sv requires SIM=verilator or SIM=icarus, got SIM=$(SIM))
    endif
    TOPLEVEL_LANG   := verilog
    VERILOG_SOURCES := \
      $(REPO_ROOT)/src/sv/uart_pkg.sv \
      $(REPO_ROOT)/src/sv/uart_core.sv
    VHDL_SOURCES    :=
    VERILOG_INCLUDE_DIRS := $(REPO_ROOT)/src/sv
else
    $(error Unknown TOPLEVEL_HDL=$(TOPLEVEL_HDL). Valid: vhdl | sv)
endif

# ── Simulator-specific flags ──────────────────────────────────────────────────
ifeq ($(SIM),ghdl)
    $(shell mkdir -p $(REPO_ROOT)/out/waves)
    SIM_ARGS += --wave=$(REPO_ROOT)/out/waves/uart_core.fst
endif

ifeq ($(SIM),verilator)
    VERILATOR_TRACE     := 1
    EXTRA_ARGS          += --trace
endif

# cocotb test file lives alongside this Makefile
export COCOTB_TEST_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
PYTHONPATH := $(COCOTB_TEST_DIR):$(PYTHONPATH)
export PYTHONPATH

include $(COCOTB_MAKEFILES)/Makefile.sim
