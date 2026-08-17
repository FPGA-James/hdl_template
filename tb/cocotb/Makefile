# cocotb simulation Makefile for <<NAME>>_core.
#
# Called by the top-level Makefile via: make -C tb/cocotb SIM= TOPLEVEL= TOPLEVEL_HDL=
#
# Supported combinations:
#   SIM=ghdl       TOPLEVEL_HDL=vhdl  — VHDL via GHDL + VHPI
#   SIM=verilator  TOPLEVEL_HDL=sv    — SystemVerilog via Verilator + VPI
#   SIM=icarus     TOPLEVEL_HDL=sv    — SystemVerilog via Icarus Verilog + VPI
#
# The top-level for cocotb tests is <<NAME>>_core (not _top), so the AXI-Lite
# register block is not involved and no hdl-modules dependency is needed.

COCOTB_MAKEFILES := $(shell cocotb-config --makefiles)

# ── Configurable variables (passed in from top-level Makefile) ────────────────
SIM          ?= ghdl
TOPLEVEL     ?= <<NAME>>_core
TOPLEVEL_HDL ?= vhdl
MODULE       ?= test_NAME
REPO_ROOT    := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))../..)

# ── Compatibility guard ────────────────────────────────────────────────────────
ifeq ($(TOPLEVEL_HDL),vhdl)
    ifeq ($(filter ghdl,$(SIM)),)
        $(error TOPLEVEL_HDL=vhdl requires SIM=ghdl, got SIM=$(SIM))
    endif
    TOPLEVEL_LANG   := vhdl
    VHDL_SOURCES    := \
      $(REPO_ROOT)/src/vhdl/<<NAME>>_pkg.vhd \
      $(REPO_ROOT)/src/vhdl/<<NAME>>_core.vhd
    VERILOG_SOURCES :=
    COMPILE_ARGS    += --std=08
else ifeq ($(TOPLEVEL_HDL),sv)
    ifeq ($(filter verilator icarus,$(SIM)),)
        $(error TOPLEVEL_HDL=sv requires SIM=verilator or SIM=icarus, got SIM=$(SIM))
    endif
    TOPLEVEL_LANG   := verilog
    VERILOG_SOURCES := \
      $(REPO_ROOT)/src/sv/<<NAME>>_pkg.sv \
      $(REPO_ROOT)/src/sv/<<NAME>>_core.sv
    VHDL_SOURCES    :=
    VERILOG_INCLUDE_DIRS := $(REPO_ROOT)/src/sv
else
    $(error Unknown TOPLEVEL_HDL=$(TOPLEVEL_HDL). Valid: vhdl | sv)
endif

# ── Simulator-specific flags ──────────────────────────────────────────────────
ifeq ($(SIM),ghdl)
    SIM_ARGS += --wave=$(REPO_ROOT)/waves/$(TOPLEVEL).fst
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
