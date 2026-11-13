# =============================================================================
# scripts/mk/core.mk — environment, shared file lists and macros
#
# Included first by the top-level Makefile. Everything here is tool-agnostic
# plumbing used by more than one flow; tool-specific logic lives in scripts/mk/tools/.
# =============================================================================

# Captured before PATH is overridden below: OSS CAD Suite bundles its own
# python3 in py3bin/ (a stripped build with no working ensurepip), which
# would otherwise shadow the interpreter the caller actually intended
# (pyenv, a CI-pinned setup-python version, etc.) for `make venv`'s own
# `python3 -m venv` bootstrap step. := evaluates $(shell ...) immediately,
# using the PATH make itself inherited from its caller, not the exported
# PATH below.
SYSTEM_PYTHON3 := $(shell command -v python3)

# ── OSS CAD Suite ─────────────────────────────────────────────────────────────
# Path to the OSS CAD Suite install (bundles GHDL, Yosys, Verilator, Icarus).
# Override with: make sim OSS_CAD_SUITE=/path/to/oss-cad-suite
OSS_CAD_SUITE ?= $(HOME)/tools/oss-cad-suite
# Mirror what `source environment` does: extend PATH and set tool prefixes.
# .venv/bin goes first so cocotb's own sub-Makefiles can find cocotb-config
# via bare PATH lookup (tb/cocotb/Makefile shells out to it directly) --
# $(PYTHON) alone only covers explicit python invocations, not this. Must be
# $(CURDIR)-absolute, not a bare relative "./.venv/bin": tb/cocotb/Makefile
# runs via `$(MAKE) -C tb/cocotb`, which changes the shell's cwd, so a
# relative entry silently resolves to nothing there and PATH search falls
# through to OSS CAD Suite's own bundled cocotb-config -- which brings its
# own bundled cocotb (matched to its own bundled Python/VPI libs) instead of
# the pinned one this project's requirements.txt installs into .venv.
export PATH         := $(CURDIR)/.venv/bin:$(OSS_CAD_SUITE)/bin:$(OSS_CAD_SUITE)/py3bin:$(PATH)
export GHDL_PREFIX  ?= $(OSS_CAD_SUITE)/lib/ghdl
export VERILATOR_ROOT ?= $(OSS_CAD_SUITE)/share/verilator

# ── Bender-generated file lists (evaluated lazily) ───────────────────────────
VHDL_RTL  = $(shell $(BENDER) script flist -t rtl_vhdl  --no-default-target 2>/dev/null)
SV_RTL    = $(shell $(BENDER) script flist -t rtl_sv    --no-default-target 2>/dev/null)
VHDL_GEN  = $(shell $(BENDER) script flist -t gen_vhdl  --no-default-target 2>/dev/null)
SV_IMPL   = $(shell $(BENDER) script flist -t impl_sv   --no-default-target 2>/dev/null)
SV_GEN    = $(shell $(BENDER) script flist -t gen_sv    --no-default-target 2>/dev/null)

# ── hdl-modules VHDL packages required by the generated register file ─────────
# Compiled into named libraries before the main sources so that
# `library axi_lite` and `library register_file` resolve correctly in ghdl.
HDL_MODULES      = $(shell $(BENDER) path hdl_modules 2>/dev/null)
VHDL_AXI_LITE    = $(HDL_MODULES)/modules/axi_lite/src/axi_lite_pkg.vhd
VHDL_REG_FILE    = $(HDL_MODULES)/modules/register_file/src/register_file_pkg.vhd \
                   $(HDL_MODULES)/modules/register_file/src/axi_lite_register_file.vhd

# ── Docs register bridge ──────────────────────────────────────────────────────
# HDL AutoDoc (>= v3.8.0) reads regs_<top module>.toml from this directory to
# build each module's register page (the `regs` target copies them there). It
# lives under out/ rather than at the repo top level. autodoc.mk's own default
# is `registers`; setting it here (with ?=) before the include wins.
AUTODOC_REGISTERS_DIR ?= out/registers

# ── Build reports ─────────────────────────────────────────────────────────────
# Root for synthesis / place-and-route reports. HDL AutoDoc's Build page ingests a
# fixed layout under it, so the flows write to exactly these names:
#   yosys/yosys.log  yosys/stat.txt  yosys/nextpnr.log   (open-source flow)
#   vivado/utilization_placed.rpt  vivado/timing_summary_routed.rpt  (Vivado, later)
# autodoc.mk's own default is `reports`; setting it here (?=) before the include wins.
AUTODOC_REPORTS_DIR ?= out/reports

# Every tool also keeps what it prints, plus whatever report files it can write, in its own
# folder under out/reports/ -- named after the tool, because HDL Log Lens finds a log's parser
# from the file or folder name (verilator/ nvc/ yosys/ nextpnr ...) and reads **/out/reports/**/*.log
# and **/*.rpt. Each tool's folder variable (<TOOL>_RDIR) is defined in its own scripts/mk/tools/ file.

# ── Tool registry ─────────────────────────────────────────────────────────────
# Each scripts/mk/tools/<tool>/<tool>.mk appends itself to the lists below for the flows it
# provides and defines the matching <flow>-<tool> targets. The dispatchers in
# the flow files (sim.mk, synth.mk, impl.mk) turn `make synth` into
# `synth-$(SYNTH_TOOL)` and use these lists in their "unknown tool" errors.
# To add a tool: drop in scripts/mk/tools/<tool>/<tool>.mk — nothing else needs editing.
SYNTH_TOOLS      :=
IMPL_TOOLS       :=
SIM_NATIVE_TOOLS :=

# =============================================================================
# Macros
# =============================================================================

# bash, not /bin/sh: run-logged below needs PIPESTATUS.
SHELL := bash

# run-logged — run a command, show its output as usual and keep a copy (stdout + stderr) in a
# log file for HDL Log Lens; the exit status is the command's, not tee's.
# $(1) = log file  $(2) = command (a `&&` chain or a pipeline is fine)
define run-logged
	@mkdir -p $(dir $(1))
	@{ $(2) ; } 2>&1 | tee $(1) ; exit $${PIPESTATUS[0]}
endef

# check-venv — abort with a clear message if the venv has not been created.
define check-venv
	@test -f .venv/bin/python3 || \
	  (printf "\n\033[1;31m  ERROR:\033[0m Python virtual environment not found.\n" && \
	   printf  "         Run '\033[36mmake venv\033[0m' first, then retry.\n\n" && \
	   exit 1)
endef

# check-submodule — abort with a clear message if submodules/HDLAutoDoc is not checked out.
define check-submodule
	@test -f $(AUTODOC_SCRIPTDIR)/parse_hierarchy.py || \
	  (printf "\n\033[1;31m  ERROR:\033[0m submodules/HDLAutoDoc is not checked out.\n" && \
	   printf  "         Run '\033[36mgit submodule update --init --recursive\033[0m' first, then retry.\n\n" && \
	   exit 1)
endef

# check-rtl-list — abort if a Bender-derived file list came back empty.
# $(1) = list content (e.g. $(VHDL_RTL))  $(2) = name for the error message (e.g. VHDL_RTL)
define check-rtl-list
	@test -n "$(1)" || \
	  (printf "\n\033[1;31m  ERROR:\033[0m Bender returned an empty $(2) file list.\n" && \
	   printf  "         Run '\033[36mmake deps\033[0m' to fetch and lock dependencies.\n\n" && \
	   exit 1)
endef

# compile-ghdl-libs — pre-compile hdl-modules into named GHDL libraries.
# $(1) = workdir path (will be created if absent)
define compile-ghdl-libs
	@mkdir -p $(1)
	@printf "  \033[2m[ghdl]\033[0m Compiling axi_lite library...\n"
	@$(OSS_CAD_SUITE)/bin/ghdl -a --std=08 --workdir=$(1) \
	  --work=axi_lite $(VHDL_AXI_LITE)
	@printf "  \033[2m[ghdl]\033[0m Compiling register_file library...\n"
	@$(OSS_CAD_SUITE)/bin/ghdl -a --std=08 --workdir=$(1) \
	  -P$(1) --work=register_file $(VHDL_REG_FILE)
endef

# unknown-tool — recipe body for the "<flow>-%" fallback rules in the flow files.
# $(1) = flow  $(2) = selector variable  $(3) = registered tools
define unknown-tool
	@printf "\n\033[1;31m  ERROR:\033[0m No '$(1)' backend '$*' ($(2)=$($(2))).\n" && \
	 printf  "         Registered: \033[36m$(3)\033[0m\n" && \
	 printf  "         Backends live in scripts/mk/tools/<tool>/<tool>.mk\n\n" && exit 1
endef
