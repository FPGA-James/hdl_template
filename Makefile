# =============================================================================
# HDL Template — Top-Level Makefile
#
# Thin entry point: user-facing variables, then the includes. The logic lives in
#   scripts/mk/core.mk     environment, Bender file lists, macros, tool registry
#   scripts/mk/<flow>.mk   setup, sim, synth, impl, docs, lint, clean, help
#   scripts/mk/tools/*.mk  one file per tool backend (yosys, nextpnr, nvc, verilator, ...)
# Run `make help` for targets. To add a tool, drop a file into scripts/mk/tools/.
# =============================================================================

# ── User-configurable variables ───────────────────────────────────────────────
# HDL language for simulation/synthesis: vhdl | sv. `make init ... TOPLEVEL_HDL=sv` rewrites
# this default to sv; FRAMEWORK and SIM below follow it.
TOPLEVEL_HDL ?= vhdl

# Normalised language key used to pick per-language variables
# (anything other than sv is treated as vhdl, as the recipes always did).
HDL_KIND = $(if $(filter sv,$(TOPLEVEL_HDL)),sv,vhdl)

# Verification framework: vunit | cocotb | native. vunit drives VHDL only, so SV defaults to cocotb.
FRAMEWORK    ?= $(if $(filter sv,$(HDL_KIND)),cocotb,vunit)

# Simulator: ghdl | verilator (cocotb only; VUnit always uses GHDL). Follows the language.
SIM          ?= $(if $(filter sv,$(HDL_KIND)),verilator,ghdl)

# Top-level entity/module name (set by make init; matches <<NAME>>_top)
TOPLEVEL     ?= <<NAME>>_top

# Python interpreter — always use the project venv (run `make venv` first)
PYTHON       ?= .venv/bin/python3

# Bender binary (must be on PATH or set here)
BENDER       ?= bender

# Documentation title
PROJECT      ?= $(notdir $(CURDIR))

# RTL schematics in the docs (yosys + netlistsvg). On by default for SV; off for VHDL, where
# HDL AutoDoc v3.13 does not read package files before a module's schematic (every module
# using a package fails with "no declaration for ..."); SCHEMATICS=1 forces them on.
SCHEMATICS   ?= $(if $(filter sv,$(HDL_KIND)),1,0)

# ── Includes ──────────────────────────────────────────────────────────────────
# Order matters only for the help sections (file order) and for core.mk, which
# must come first (tool registry, macros). Tool backends are picked up by
# wildcard; flows dispatch to them by name (SYNTH_TOOL, IMPL_TOOL, NATIVE_SIM).
include scripts/mk/core.mk
include $(sort $(wildcard scripts/mk/tools/*.mk))
include scripts/mk/setup.mk
include scripts/mk/sim.mk
include scripts/mk/synth.mk
include scripts/mk/impl.mk
include scripts/mk/docs.mk
include scripts/mk/lint.mk
include scripts/mk/clean.mk
include scripts/mk/help.mk

all: regs sim

# docs.mk pulls in autodoc.mk, which defines targets, so pin the default goal.
.DEFAULT_GOAL := all
