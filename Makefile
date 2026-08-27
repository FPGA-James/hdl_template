# =============================================================================
# HDL Template — Top-Level Makefile
# =============================================================================

# ── OSS CAD Suite ─────────────────────────────────────────────────────────────
# Path to the OSS CAD Suite install (bundles GHDL, Yosys, Verilator, Icarus).
# Override with: make sim OSS_CAD_SUITE=/path/to/oss-cad-suite
OSS_CAD_SUITE ?= $(HOME)/tools/oss-cad-suite
# Mirror what `source environment` does: extend PATH and set tool prefixes.
export PATH         := $(OSS_CAD_SUITE)/bin:$(OSS_CAD_SUITE)/py3bin:$(PATH)
export GHDL_PREFIX  ?= $(OSS_CAD_SUITE)/lib/ghdl
export VERILATOR_ROOT ?= $(OSS_CAD_SUITE)/share/verilator

# ── User-configurable variables ───────────────────────────────────────────────
# Verification framework: vunit | cocotb | native
FRAMEWORK    ?= cocotb

# Simulator: ghdl | verilator | icarus
SIM          ?= verilator

# HDL language for simulation/synthesis: vhdl | sv
TOPLEVEL_HDL ?= sv

# Top-level entity/module name (set by make init; matches <<NAME>>_top)
TOPLEVEL     ?= <<NAME>>_top

# Python interpreter — always use the project venv (run `make venv` first)
PYTHON       ?= .venv/bin/python3

# Bender binary (must be on PATH or set here)
BENDER       ?= bender

# NVC binary — native (framework-less) VHDL simulator, used only by
# `make sim-native TOPLEVEL_HDL=vhdl`. Not part of OSS CAD Suite; install
# separately (e.g. `brew install nvc` or https://www.nickg.me.uk/nvc/).
NVC          ?= nvc

# IceStudio application name / binary
# macOS: app bundle name passed to `open -a`  (default: IceStudio)
# Linux: binary name on PATH                   (default: icestudio)
ICESTUDIO    ?= IceStudio

# Documentation title
PROJECT      ?= $(notdir $(CURDIR))

# Set to 1 to include RTL schematics in docs (requires yosys + ghdl-yosys-plugin)
SCHEMATICS   ?= 0

# ── HDL AutoDoc pipeline variables ───────────────────────────────────────────
AUTODOC_SPHINXBUILD    = $(PYTHON) -m sphinx
AUTODOC_SOURCEDIR      = docs
AUTODOC_BUILDDIR       = out/docs
AUTODOC_SCRIPTDIR      = submodules/HDLAutoDoc/src/scripts/hdl_autodoc
AUTODOC_FILELIST       = filelist.f
AUTODOC_HIERARCHY_JSON = $(AUTODOC_SOURCEDIR)/hierarchy.json
AUTODOC_LIBDIR         = out/ghdl_libs
AUTODOC_REPORTSDIR     = out/reports

# ── Bender-generated file lists (evaluated lazily) ───────────────────────────
VHDL_RTL  = $(shell $(BENDER) script flist -t rtl_vhdl  --no-default-target 2>/dev/null)
SV_RTL    = $(shell $(BENDER) script flist -t rtl_sv    --no-default-target 2>/dev/null)
VHDL_GEN  = $(shell $(BENDER) script flist -t gen_vhdl  --no-default-target 2>/dev/null)
SV_GEN    = $(shell $(BENDER) script flist -t gen_sv    --no-default-target 2>/dev/null)

# ── hdl-modules VHDL packages required by the generated register file ─────────
# Compiled into named libraries before the main sources so that
# `library axi_lite` and `library register_file` resolve correctly in ghdl.
HDL_MODULES      = $(shell $(BENDER) path hdl_modules 2>/dev/null)
VHDL_AXI_LITE    = $(HDL_MODULES)/modules/axi_lite/src/axi_lite_pkg.vhd
VHDL_REG_FILE    = $(HDL_MODULES)/modules/register_file/src/register_file_pkg.vhd \
                   $(HDL_MODULES)/modules/register_file/src/axi_lite_register_file.vhd

# =============================================================================
# Phony targets
# =============================================================================
.PHONY: all venv install init deps lsp vhdl-ls verible-ls filelist regs \
        sim sim-vunit sim-vunit-gui sim-cocotb sim-native sim-native-vhdl sim-native-sv \
        synth synth-gui impl impl-gui icestudio \
        hierarchy scaffold extract coverage reports html pdf doc \
        lint lint-vhdl lint-sv \
        test-autodoc \
        clean clean-generated clean-all \
        vars help

all: regs sim

# =============================================================================
# Macros
# =============================================================================

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

# check-nvc — abort with a clear message if NVC is not on PATH. NVC is not
# part of OSS CAD Suite and must be installed separately.
define check-nvc
	@command -v $(NVC) >/dev/null 2>&1 || \
	  (printf "\n\033[1;31m  ERROR:\033[0m NVC not found (checked '\033[36m$(NVC)\033[0m').\n" && \
	   printf  "         Install NVC (e.g. '\033[36mbrew install nvc\033[0m' or https://www.nickg.me.uk/nvc/)\n" && \
	   printf  "         or override the binary path: \033[36mmake sim-native NVC=/path/to/nvc\033[0m\n\n" && \
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

# =============================================================================
# Setup
# =============================================================================

##@ Setup

venv: ## Create .venv and install all Python deps (run once)
	@printf "\n\033[1m  Setting up Python virtual environment...\033[0m\n\n"
	@python3 -m venv .venv
	@.venv/bin/python3 -m ensurepip --upgrade >/dev/null
	@.venv/bin/python3 -m pip install --upgrade pip -q
	@.venv/bin/python3 -m pip install -r requirements.txt -q
	@printf "\n\033[32m  ✓\033[0m Virtual environment ready — targets use .venv/bin/python3 directly.\n\n"

install: ## Upgrade Python deps in the active venv
	$(call check-venv)
	@$(PYTHON) -m pip install --upgrade -r requirements.txt -q

init: ## Replace <<NAME>> placeholders and rename files  [NAME=<project>  TOPLEVEL_HDL=vhdl|sv]
	@test -n "$(NAME)" || \
	  (printf "\n\033[1;31m  ERROR:\033[0m Specify a project name: \033[36mmake init NAME=my_module\033[0m\n\n" && exit 1)
	@bash scripts/init_project.sh $(NAME) $(TOPLEVEL_HDL)

vars: ## Print all current variable values
	@printf "\n\033[1m  Current variable values\033[0m\n\n"
	@printf "    \033[36m%-22s\033[0m %s\n" \
	  "OSS_CAD_SUITE"    "$(OSS_CAD_SUITE)" \
	  "FRAMEWORK"        "$(FRAMEWORK)" \
	  "SIM"              "$(SIM)" \
	  "TOPLEVEL_HDL"     "$(TOPLEVEL_HDL)" \
	  "TOPLEVEL"         "$(TOPLEVEL)" \
	  "SCHEMATICS"       "$(SCHEMATICS)" \
	  "IMPL_FAMILY"      "$(IMPL_FAMILY)" \
	  "IMPL_DEVICE"      "$(IMPL_DEVICE)" \
	  "IMPL_PACKAGE"     "$(IMPL_PACKAGE)" \
	  "IMPL_TOPLEVEL"    "$(IMPL_TOPLEVEL)" \
	  "IMPL_CONSTRAINT"  "$(IMPL_CONSTRAINT)" \
	  "ICESTUDIO"        "$(ICESTUDIO)" \
	  "PYTHON"           "$(PYTHON)"
	@printf "\n"

lsp: vhdl-ls verible-ls ## Generate all LSP config files (vhdl_ls.toml + verible.filelist)

vhdl-ls: ## Generate vhdl_ls.toml for the VHDL Language Server (requires make deps)
	$(call check-venv)
	@$(PYTHON) scripts/gen_vhdl_ls.py

verible-ls: ## Generate verible.filelist for the Verible Language Server (requires make deps)
	$(call check-venv)
	@$(PYTHON) scripts/gen_verible_filelist.py

deps: ## Fetch HDL dependencies via Bender (resolved via `bender path`, not vendored into the tree)
	@printf "\n\033[1m  Fetching HDL dependencies...\033[0m\n\n"
	@$(BENDER) update
	@printf "\n\033[32m  ✓\033[0m Dependencies ready\n\n"

regs: out/regs/vhdl/.stamp ## Generate VHDL/C/HTML register files from regs/*.toml

out/regs/vhdl/.stamp: $(wildcard regs/*.toml) scripts/gen_regs.py $(wildcard src/*_core.vhd src/*_core.sv)
	$(call check-venv)
	@printf "\n\033[1m  Generating register files...\033[0m\n\n"
	@$(PYTHON) scripts/gen_regs.py
	@touch out/regs/vhdl/.stamp
	@printf "\n\033[32m  ✓\033[0m Registers generated in out/regs/\n\n"

# =============================================================================
# Simulation
# =============================================================================

##@ Simulation

sim: regs ## Run simulation  [FRAMEWORK=vunit|cocotb|native  SIM=ghdl|verilator|icarus  TOPLEVEL_HDL=vhdl|sv]
ifeq ($(FRAMEWORK),vunit)
	$(MAKE) sim-vunit
else ifeq ($(FRAMEWORK),cocotb)
	$(MAKE) sim-cocotb
else ifeq ($(FRAMEWORK),native)
	$(MAKE) sim-native
else
	$(error Unknown FRAMEWORK=$(FRAMEWORK). Valid: vunit | cocotb | native)
endif

sim-vunit: regs ## Run VUnit testbench via GHDL (VHDL only)
	$(call check-venv)
	@printf "\n\033[1m  Running VUnit simulation (GHDL)...\033[0m\n\n"
	@VUNIT_SIMULATOR=ghdl $(PYTHON) tb/vunit/run.py $(VUNIT_ARGS)

sim-vunit-gui: regs ## Open VUnit testbench in the GHDL waveform viewer
	$(call check-venv)
	@VUNIT_SIMULATOR=ghdl $(PYTHON) tb/vunit/run.py --gui $(VUNIT_ARGS)

sim-cocotb: regs ## Run cocotb testbench  [SIM=  TOPLEVEL_HDL=vhdl|sv]
	@mkdir -p waves
	@printf "\n\033[1m  Running cocotb simulation ($(SIM))...\033[0m\n\n"
	@$(MAKE) -C tb/cocotb SIM=$(SIM) TOPLEVEL_HDL=$(TOPLEVEL_HDL)

NATIVE_RDIR = out/native

sim-native: regs ## Run the native (framework-less) testbench directly with NVC (VHDL) or Verilator (SV)  [TOPLEVEL_HDL=vhdl|sv]
ifeq ($(TOPLEVEL_HDL),sv)
	$(MAKE) sim-native-sv
else
	$(MAKE) sim-native-vhdl
endif

NATIVE_NVC_LIBDIR = $(NATIVE_RDIR)/nvc_libs

sim-native-vhdl: regs ## Compile+elaborate+run tb/native/vhdl/<<NAME>>_tb.vhd directly with NVC (no framework)
	$(call check-nvc)
	@printf "\n\033[1m  Running native VHDL simulation (NVC)...\033[0m\n\n"
	@mkdir -p $(NATIVE_NVC_LIBDIR) $(NATIVE_RDIR)/nvc_work
	@printf "  \033[2m[nvc]\033[0m Compiling axi_lite library...\n"
	@$(NVC) --std=2008 --work=axi_lite:$(NATIVE_NVC_LIBDIR)/axi_lite -a \
	  $(VHDL_AXI_LITE)
	@printf "  \033[2m[nvc]\033[0m Compiling register_file library...\n"
	@$(NVC) --std=2008 --work=register_file:$(NATIVE_NVC_LIBDIR)/register_file \
	  -L $(NATIVE_NVC_LIBDIR) -a $(VHDL_REG_FILE)
	@$(NVC) --std=2008 --work=$(NATIVE_RDIR)/nvc_work -L $(NATIVE_NVC_LIBDIR) -a \
	  $(VHDL_GEN) $(VHDL_RTL) tb/native/vhdl/<<NAME>>_tb.vhd
	@$(NVC) --work=$(NATIVE_RDIR)/nvc_work -L $(NATIVE_NVC_LIBDIR) -e <<NAME>>_tb
	@$(NVC) --work=$(NATIVE_RDIR)/nvc_work -L $(NATIVE_NVC_LIBDIR) -r <<NAME>>_tb
	@printf "\n\033[32m  ✓\033[0m Native VHDL simulation passed\n\n"

sim-native-sv: regs ## Compile+run tb/native/sv/<<NAME>>_tb.sv directly with Verilator --binary (no framework)
	@printf "\n\033[1m  Running native SystemVerilog simulation (Verilator)...\033[0m\n\n"
	@mkdir -p $(NATIVE_RDIR)/verilator_obj
	@$(OSS_CAD_SUITE)/bin/verilator --binary --timing -Wall -Wno-fatal -j 0 \
	  -Mdir $(NATIVE_RDIR)/verilator_obj --top-module <<NAME>>_tb \
	  tb/native/sv/axi_lite_driver_pkg.sv \
	  src/sv/<<NAME>>_pkg.sv \
	  $(SV_GEN) \
	  src/sv/<<NAME>>_core.sv src/sv/<<NAME>>_top.sv \
	  tb/native/sv/<<NAME>>_tb.sv
	@$(NATIVE_RDIR)/verilator_obj/V<<NAME>>_tb
	@printf "\n\033[32m  ✓\033[0m Native SystemVerilog simulation passed\n\n"

# =============================================================================
# Synthesis
# =============================================================================

##@ Synthesis

SYNTH_RDIR = out/reports/synth

synth: regs ## Synthesise with Yosys  [TOPLEVEL_HDL=vhdl|sv]
	@mkdir -p out/synth $(SYNTH_RDIR)
ifeq ($(TOPLEVEL_HDL),sv)
	$(call check-rtl-list,$(SV_RTL),SV_RTL)
	@printf "\n\033[1m  Synthesising $(TOPLEVEL) (SystemVerilog → Xilinx xc7)...\033[0m\n\n"
	@$(OSS_CAD_SUITE)/bin/yosys -q \
	  -l "$(SYNTH_RDIR)/$(TOPLEVEL)_sv_synth.log" \
	  -p "read_verilog -sv $(SV_GEN) $(SV_RTL)" \
	  -p "synth_xilinx -family xc7 -top $(TOPLEVEL) -edif out/synth/$(TOPLEVEL)_sv.edif" \
	  -p "tee -o $(SYNTH_RDIR)/$(TOPLEVEL)_sv_check.txt check" \
	  -p "tee -o $(SYNTH_RDIR)/$(TOPLEVEL)_sv_util.txt stat -tech xilinx" \
	  -p "write_json $(SYNTH_RDIR)/$(TOPLEVEL)_sv.json"
	@printf "\n\033[32m  ✓\033[0m Netlist:  \033[36mout/synth/$(TOPLEVEL)_sv.edif\033[0m\n"
	@printf "    Reports: \033[36m$(SYNTH_RDIR)/$(TOPLEVEL)_sv_*\033[0m\n\n"
else
	$(call check-rtl-list,$(VHDL_RTL),VHDL_RTL)
	@printf "\n\033[1m  Synthesising $(TOPLEVEL) (VHDL → Xilinx xc7)...\033[0m\n\n"
	$(call compile-ghdl-libs,out/synth/workdir)
	@printf "  \033[2m[yosys]\033[0m Elaborating and synthesising...\n"
	@$(OSS_CAD_SUITE)/bin/yosys -q \
	  -l "$(SYNTH_RDIR)/$(TOPLEVEL)_vhdl_synth.log" \
	  -p "plugin -i ghdl" \
	  -p "ghdl --std=08 -Pout/synth/workdir $(VHDL_RTL) $(VHDL_GEN) -e $(TOPLEVEL)" \
	  -p "synth_xilinx -family xc7 -top $(TOPLEVEL) -edif out/synth/$(TOPLEVEL)_vhdl.edif" \
	  -p "tee -o $(SYNTH_RDIR)/$(TOPLEVEL)_vhdl_check.txt check" \
	  -p "tee -o $(SYNTH_RDIR)/$(TOPLEVEL)_vhdl_util.txt stat -tech xilinx" \
	  -p "write_json $(SYNTH_RDIR)/$(TOPLEVEL)_vhdl.json"
	@printf "\n\033[32m  ✓\033[0m Netlist:  \033[36mout/synth/$(TOPLEVEL)_vhdl.edif\033[0m\n"
	@printf "    Reports: \033[36m$(SYNTH_RDIR)/$(TOPLEVEL)_vhdl_*\033[0m\n\n"
endif

synth-gui: synth ## Open Yosys schematic viewer for the last synthesis  [TOPLEVEL_HDL=vhdl|sv]
	@printf "\n\033[1m  Opening Yosys schematic viewer...\033[0m\n\n"
	@$(OSS_CAD_SUITE)/bin/yosys \
	  -p "read_json $(SYNTH_RDIR)/$(TOPLEVEL)_$(TOPLEVEL_HDL).json; show $(TOPLEVEL)"

# =============================================================================
# Implementation (nextpnr place-and-route)
# =============================================================================

# FPGA family for nextpnr.  Determines the synth command, nextpnr binary,
# constraint file format, and bitstream packer.
#   ice40   → nextpnr-ice40  + icepack   (constraint: .pcf)
#   ecp5    → nextpnr-ecp5   + ecppack   (constraint: .lpf)
#   machxo2 → nextpnr-machxo2 + ddtcmd  (constraint: .lpf)
IMPL_FAMILY     ?= ice40

# Device and package — must match your physical FPGA.
# ice40 examples:  IMPL_DEVICE=hx8k   IMPL_PACKAGE=ct256
#                  IMPL_DEVICE=hx1k   IMPL_PACKAGE=tq144
# ecp5 examples:   IMPL_DEVICE=lfe5u-25f  IMPL_PACKAGE=CABGA256
IMPL_DEVICE     ?= hx8k
IMPL_PACKAGE    ?= ct256

# Top-level module for implementation.  Defaults to <<NAME>>_core (not
# <<NAME>>_top) because <<NAME>>_top exposes the full AXI-Lite bus which
# typically exceeds iCE40 IO limits.  Override if your design's port count
# fits the target device IO.
IMPL_TOPLEVEL   ?= <<NAME>>_core

# Constraint file (.pcf for ice40, .lpf for ecp5/machxo2).
IMPL_CONSTRAINT ?= synth/constraints/$(IMPL_TOPLEVEL).$(if $(filter ecp5 machxo2,$(IMPL_FAMILY)),lpf,pcf)

##@ Implementation

IMPL_RDIR = out/reports/impl
IMPL_STEM = $(IMPL_TOPLEVEL)_$(IMPL_FAMILY)

impl: regs ## Place-and-route with nextpnr  [IMPL_FAMILY=ice40|ecp5  IMPL_DEVICE=  IMPL_PACKAGE=  TOPLEVEL_HDL=vhdl|sv]
	@mkdir -p out/impl $(IMPL_RDIR)
	@printf "\n\033[1m  Synthesising $(IMPL_TOPLEVEL) for $(IMPL_FAMILY) ($(IMPL_DEVICE)/$(IMPL_PACKAGE))...\033[0m\n\n"
ifeq ($(TOPLEVEL_HDL),sv)
	$(call check-rtl-list,$(SV_RTL),SV_RTL)
	@$(OSS_CAD_SUITE)/bin/yosys -q \
	  -l "$(IMPL_RDIR)/$(IMPL_STEM)_synth.log" \
	  -p "read_verilog -sv $(SV_GEN) $(SV_RTL)" \
	  -p "synth_$(IMPL_FAMILY) -top $(IMPL_TOPLEVEL) -json out/impl/$(IMPL_STEM).json"
else
	$(call check-rtl-list,$(VHDL_RTL),VHDL_RTL)
	$(call compile-ghdl-libs,out/synth/workdir)
	@printf "  \033[2m[yosys]\033[0m Elaborating and mapping to $(IMPL_FAMILY)...\n"
	@$(OSS_CAD_SUITE)/bin/yosys -q \
	  -l "$(IMPL_RDIR)/$(IMPL_STEM)_synth.log" \
	  -p "plugin -i ghdl" \
	  -p "ghdl --std=08 -Pout/synth/workdir $(VHDL_RTL) $(VHDL_GEN) -e $(TOPLEVEL)" \
	  -p "synth_$(IMPL_FAMILY) -top $(IMPL_TOPLEVEL) -json out/impl/$(IMPL_STEM).json"
endif
	@printf "  \033[2m[nextpnr]\033[0m Place and route...\n"
ifeq ($(IMPL_FAMILY),ice40)
	@$(OSS_CAD_SUITE)/bin/nextpnr-ice40 -q \
	  --$(IMPL_DEVICE) --package $(IMPL_PACKAGE) \
	  --json   "out/impl/$(IMPL_STEM).json" \
	  --pcf    "$(IMPL_CONSTRAINT)" \
	  --pcf-allow-unconstrained \
	  --asc    "out/impl/$(IMPL_TOPLEVEL).asc" \
	  --write  "$(IMPL_RDIR)/$(IMPL_STEM)_routed.json" \
	  --report "$(IMPL_RDIR)/$(IMPL_STEM)_timing.json" \
	  --detailed-timing-report \
	  --sdf    "$(IMPL_RDIR)/$(IMPL_STEM)_routed.sdf" \
	  --placed-svg "$(IMPL_RDIR)/$(IMPL_STEM)_placed.svg" \
	  --routed-svg "$(IMPL_RDIR)/$(IMPL_STEM)_routed.svg" \
	  -l       "$(IMPL_RDIR)/$(IMPL_STEM)_pnr.log"
	@printf "  \033[2m[icepack]\033[0m Packing bitstream...\n"
	@$(OSS_CAD_SUITE)/bin/icepack "out/impl/$(IMPL_TOPLEVEL).asc" "out/impl/$(IMPL_TOPLEVEL).bit"
else ifeq ($(IMPL_FAMILY),ecp5)
	@$(OSS_CAD_SUITE)/bin/nextpnr-ecp5 -q \
	  --$(IMPL_DEVICE) --package $(IMPL_PACKAGE) \
	  --json      "out/impl/$(IMPL_STEM).json" \
	  --lpf       "$(IMPL_CONSTRAINT)" \
	  --textcfg   "out/impl/$(IMPL_TOPLEVEL).config" \
	  --write     "$(IMPL_RDIR)/$(IMPL_STEM)_routed.json" \
	  --report    "$(IMPL_RDIR)/$(IMPL_STEM)_timing.json" \
	  --detailed-timing-report \
	  --sdf       "$(IMPL_RDIR)/$(IMPL_STEM)_routed.sdf" \
	  --placed-svg "$(IMPL_RDIR)/$(IMPL_STEM)_placed.svg" \
	  --routed-svg "$(IMPL_RDIR)/$(IMPL_STEM)_routed.svg" \
	  -l          "$(IMPL_RDIR)/$(IMPL_STEM)_pnr.log"
	@printf "  \033[2m[ecppack]\033[0m Packing bitstream...\n"
	@$(OSS_CAD_SUITE)/bin/ecppack --compress "out/impl/$(IMPL_TOPLEVEL).config" "out/impl/$(IMPL_TOPLEVEL).bit"
else ifeq ($(IMPL_FAMILY),machxo2)
	@$(OSS_CAD_SUITE)/bin/nextpnr-machxo2 -q \
	  --$(IMPL_DEVICE) --package $(IMPL_PACKAGE) \
	  --json      "out/impl/$(IMPL_STEM).json" \
	  --lpf       "$(IMPL_CONSTRAINT)" \
	  --textcfg   "out/impl/$(IMPL_TOPLEVEL).config" \
	  --write     "$(IMPL_RDIR)/$(IMPL_STEM)_routed.json" \
	  --report    "$(IMPL_RDIR)/$(IMPL_STEM)_timing.json" \
	  --detailed-timing-report \
	  --sdf       "$(IMPL_RDIR)/$(IMPL_STEM)_routed.sdf" \
	  --placed-svg "$(IMPL_RDIR)/$(IMPL_STEM)_placed.svg" \
	  --routed-svg "$(IMPL_RDIR)/$(IMPL_STEM)_routed.svg" \
	  -l          "$(IMPL_RDIR)/$(IMPL_STEM)_pnr.log"
	@printf "  \033[2m[ddtcmd]\033[0m Packing bitstream...\n"
	@$(OSS_CAD_SUITE)/bin/ddtcmd -oft -bit -if "out/impl/$(IMPL_TOPLEVEL).config" -of "out/impl/$(IMPL_TOPLEVEL).bit"
else
	$(error Unknown IMPL_FAMILY=$(IMPL_FAMILY). Valid: ice40 | ecp5 | machxo2)
endif
	@printf "\n\033[32m  ✓\033[0m Bitstream: \033[36mout/impl/$(IMPL_TOPLEVEL).bit\033[0m\n"
	@printf "    Reports: \033[36m$(IMPL_RDIR)/$(IMPL_STEM)_*\033[0m\n\n"

impl-gui: regs ## Open nextpnr interactive placement/routing GUI  [IMPL_FAMILY=ice40|ecp5|machxo2  TOPLEVEL_HDL=vhdl|sv]
	@mkdir -p out/impl $(IMPL_RDIR)
	@printf "\n\033[1m  Synthesising $(IMPL_TOPLEVEL) for $(IMPL_FAMILY) (GUI mode)...\033[0m\n\n"
ifeq ($(TOPLEVEL_HDL),sv)
	$(call check-rtl-list,$(SV_RTL),SV_RTL)
	@$(OSS_CAD_SUITE)/bin/yosys -q \
	  -l "$(IMPL_RDIR)/$(IMPL_STEM)_synth.log" \
	  -p "read_verilog -sv $(SV_GEN) $(SV_RTL)" \
	  -p "synth_$(IMPL_FAMILY) -top $(IMPL_TOPLEVEL) -json out/impl/$(IMPL_STEM).json"
else
	$(call check-rtl-list,$(VHDL_RTL),VHDL_RTL)
	$(call compile-ghdl-libs,out/synth/workdir)
	@printf "  \033[2m[yosys]\033[0m Elaborating and mapping to $(IMPL_FAMILY)...\n"
	@$(OSS_CAD_SUITE)/bin/yosys -q \
	  -l "$(IMPL_RDIR)/$(IMPL_STEM)_synth.log" \
	  -p "plugin -i ghdl" \
	  -p "ghdl --std=08 -Pout/synth/workdir $(VHDL_RTL) $(VHDL_GEN) -e $(TOPLEVEL)" \
	  -p "synth_$(IMPL_FAMILY) -top $(IMPL_TOPLEVEL) -json out/impl/$(IMPL_STEM).json"
endif
	@printf "  \033[2m[nextpnr]\033[0m Opening GUI...\n\n"
ifeq ($(IMPL_FAMILY),ice40)
	@$(OSS_CAD_SUITE)/bin/nextpnr-ice40 --gui \
	  --$(IMPL_DEVICE) --package $(IMPL_PACKAGE) \
	  --json "out/impl/$(IMPL_STEM).json" \
	  --pcf  "$(IMPL_CONSTRAINT)" \
	  --pcf-allow-unconstrained
else ifeq ($(IMPL_FAMILY),ecp5)
	@$(OSS_CAD_SUITE)/bin/nextpnr-ecp5 --gui \
	  --$(IMPL_DEVICE) --package $(IMPL_PACKAGE) \
	  --json "out/impl/$(IMPL_STEM).json" \
	  --lpf  "$(IMPL_CONSTRAINT)"
else ifeq ($(IMPL_FAMILY),machxo2)
	@$(OSS_CAD_SUITE)/bin/nextpnr-machxo2 --gui \
	  --$(IMPL_DEVICE) --package $(IMPL_PACKAGE) \
	  --json "out/impl/$(IMPL_STEM).json" \
	  --lpf  "$(IMPL_CONSTRAINT)"
else
	$(error Unknown IMPL_FAMILY=$(IMPL_FAMILY). Valid: ice40 | ecp5 | machxo2)
endif

icestudio: impl ## Run full impl then open IceStudio for device programming
	@printf "\n\033[1m  Opening IceStudio...\033[0m\n"
	@printf "    Bitstream: \033[36mout/impl/$(IMPL_TOPLEVEL).bit\033[0m\n\n"
ifeq ($(shell uname),Darwin)
	@open -a "$(ICESTUDIO)" 2>/dev/null || \
	  (printf "\n\033[1;31m  ERROR:\033[0m IceStudio not found.\n" && \
	   printf  "         Install from \033[36mhttps://icestudio.io\033[0m\n" && \
	   printf  "         or override: \033[36mmake icestudio ICESTUDIO=/path/to/IceStudio\033[0m\n\n" && \
	   exit 1)
else
	@$(ICESTUDIO) 2>/dev/null || \
	  (printf "\n\033[1;31m  ERROR:\033[0m IceStudio not found.\n" && \
	   printf  "         Install from \033[36mhttps://icestudio.io\033[0m\n" && \
	   printf  "         or override: \033[36mmake icestudio ICESTUDIO=icestudio\033[0m\n\n" && \
	   exit 1)
endif

# =============================================================================
# Documentation
# =============================================================================

##@ Documentation

html: regs extract ## Build full Sphinx HTML documentation
	$(call check-venv)
	@mkdir -p $(AUTODOC_SOURCEDIR)/_static $(AUTODOC_SOURCEDIR)/_templates
	@printf "\n\033[1m  Building HTML documentation...\033[0m\n\n"
	@$(PYTHON) $(AUTODOC_SCRIPTDIR)/include_registers.py . $(AUTODOC_SOURCEDIR)
	@$(AUTODOC_SPHINXBUILD) -M html $(AUTODOC_SOURCEDIR) $(AUTODOC_BUILDDIR)
	@printf "\n\033[32m  ✓\033[0m Documentation: \033[36m$(AUTODOC_BUILDDIR)/html/index.html\033[0m\n\n"

pdf: regs extract ## Build PDF documentation via LaTeX
	$(call check-venv)
	@printf "\n\033[1m  Building PDF documentation...\033[0m\n\n"
	@$(PYTHON) $(AUTODOC_SCRIPTDIR)/include_registers.py . $(AUTODOC_SOURCEDIR)
	@$(AUTODOC_SPHINXBUILD) -M latexpdf $(AUTODOC_SOURCEDIR) $(AUTODOC_BUILDDIR)

doc: html pdf ## Build both HTML and PDF documentation

# Internal doc pipeline stages (not shown in help)
filelist:
	@bash scripts/gen_filelist.sh > $(AUTODOC_FILELIST)

hierarchy: filelist
	$(call check-venv)
	$(call check-submodule)
	@$(PYTHON) $(AUTODOC_SCRIPTDIR)/parse_hierarchy.py \
	  $(AUTODOC_FILELIST) $(AUTODOC_HIERARCHY_JSON)

scaffold: hierarchy
	@$(PYTHON) $(AUTODOC_SCRIPTDIR)/generate_rst.py \
	  src $(AUTODOC_SOURCEDIR) "$(PROJECT)"

extract: scaffold
ifeq ($(SCHEMATICS),1)
	@printf "\n\033[1m  Extracting design information (with schematics)...\033[0m\n\n"
	$(call compile-ghdl-libs,$(AUTODOC_LIBDIR))
else
	@printf "\n\033[1m  Extracting design information...\033[0m\n\n"
endif
	@$(PYTHON) $(AUTODOC_SCRIPTDIR)/run_extract.py \
	  $(AUTODOC_HIERARCHY_JSON) $(AUTODOC_SOURCEDIR) $(AUTODOC_SCRIPTDIR) \
	  $(if $(filter 1,$(SCHEMATICS)),--schematics --ghdl-lib-path $(AUTODOC_LIBDIR))
	@$(PYTHON) $(AUTODOC_SCRIPTDIR)/generate_rst.py \
	  src $(AUTODOC_SOURCEDIR) "$(PROJECT)"

coverage: hierarchy ## Generate documentation coverage report (docs/coverage.rst)
	@printf "\n\033[1m  Generating documentation coverage report...\033[0m\n\n"
	@$(PYTHON) $(AUTODOC_SCRIPTDIR)/generate_coverage.py \
	  $(AUTODOC_HIERARCHY_JSON) $(AUTODOC_SOURCEDIR)
	@$(PYTHON) $(AUTODOC_SCRIPTDIR)/generate_rst.py \
	  src $(AUTODOC_SOURCEDIR) "$(PROJECT)"

reports: hierarchy ## Ingest synthesis/PnR reports from out/reports/ into the docs  (run after make synth/impl)
	@printf "\n\033[1m  Ingesting synthesis reports...\033[0m\n\n"
	@$(PYTHON) $(AUTODOC_SCRIPTDIR)/extract_reports.py \
	  $(AUTODOC_HIERARCHY_JSON) $(AUTODOC_SOURCEDIR) $(AUTODOC_REPORTSDIR)
	@$(PYTHON) $(AUTODOC_SCRIPTDIR)/generate_rst.py \
	  src $(AUTODOC_SOURCEDIR) "$(PROJECT)"

# =============================================================================
# Linting
# =============================================================================

##@ Linting

lint: lint-vhdl lint-sv ## Run all linters (VHDL and SV)

lint-vhdl: regs ## GHDL analysis (type/syntax) + vsg style guide
	$(call check-venv)
	@printf "\n\033[1m  Linting VHDL...\033[0m\n\n"
	$(call compile-ghdl-libs,out/synth/workdir)
	@$(OSS_CAD_SUITE)/bin/ghdl -a --std=08 --work=work -Pout/synth/workdir $(VHDL_GEN) $(VHDL_RTL)
	@$(PYTHON) -m vsg --configuration vsg.yml --filename $(VHDL_RTL)
	@printf "\n\033[32m  ✓\033[0m VHDL lint passed\n\n"

lint-sv: ## Verilator lint-only pass with all warnings enabled
	@printf "\n\033[1m  Linting SystemVerilog...\033[0m\n\n"
	@$(BENDER) script verilator -t rtl_sv -t gen_sv 2>/dev/null | \
	  xargs $(OSS_CAD_SUITE)/bin/verilator --lint-only --top-module "$(TOPLEVEL)" -Wall -Wno-fatal
	@printf "\n\033[32m  ✓\033[0m SV lint passed\n\n"

# =============================================================================
# Testing
# =============================================================================

##@ Testing

test-autodoc: ## Run the HDL AutoDoc submodule's pytest suite
	$(call check-venv)
	$(call check-submodule)
	@printf "\n\033[1m  Running HDL AutoDoc tests...\033[0m\n\n"
	@$(PYTHON) -m pytest

# =============================================================================
# Clean
# =============================================================================

##@ Clean

clean: ## Remove build outputs (out/) and sim artefacts
	@rm -rf out/docs/ out/vunit/ out/cocotb/ out/native/ out/waves/ out/ghdl_libs/ out/reports/ waves/
	@$(MAKE) -C tb/cocotb clean 2>/dev/null || true

clean-generated: clean ## Remove all generated files (out/regs/, out/synth/, out/impl/, filelist.f)
	@rm -rf out/regs/ out/synth/ out/impl/ filelist.f
	@find . \( -name "*.fst" -o -name "*.vcd" -o -name "*.ghw" -o -name "*.vvp" \) \
	  | xargs rm -f 2>/dev/null || true
	@rm -f  $(AUTODOC_HIERARCHY_JSON)
	@rm -f  $(AUTODOC_SOURCEDIR)/index.rst $(AUTODOC_SOURCEDIR)/overview.rst
	@rm -f  $(AUTODOC_SOURCEDIR)/hierarchy.rst $(AUTODOC_SOURCEDIR)/hierarchy.dot
	@rm -f  $(AUTODOC_SOURCEDIR)/registers.rst
	@rm -f  $(AUTODOC_SOURCEDIR)/coverage.rst
	@rm -rf $(AUTODOC_SOURCEDIR)/synthesis
	@rm -rf $(AUTODOC_SOURCEDIR)/_static/registers
	@if [ -d $(AUTODOC_SOURCEDIR)/modules ]; then \
	  find $(AUTODOC_SOURCEDIR)/modules -maxdepth 2 \
	    -name "index.rst" -o -name "fsm.rst" -o -name "timing.rst" \
	    -o -name "cdc.rst" -o -name "*_cdc.rst" -o -name "*_cdc.dot" \
	    -o -name "block.rst" -o -name "*_block.rst" -o -name "*_block.dot" \
	    -o -name "*_schematic.svg" \
	    -o -name "reset.rst" -o -name "*_reset.rst" -o -name "*_reset.dot" \
	    -o -name "synthesis.rst" \
	    -o -name "*.dot" -o -name "*.rst" -path "*/processes/*" \
	  | xargs rm -f 2>/dev/null; \
	  find $(AUTODOC_SOURCEDIR)/modules -maxdepth 2 -name "processes" -type d \
	  | xargs rm -rf 2>/dev/null; \
	fi

clean-all: clean-generated ## Full reset including .venv/
	@rm -rf $(AUTODOC_SOURCEDIR)/modules __pycache__
	@rm -rf .venv/

# =============================================================================
# Help
# =============================================================================

help: ## Show this help
	@awk ' \
	  BEGIN { \
	    FS = ":.*##"; \
	    BOLD = "\033[1m"; CYAN = "\033[36m"; DIM = "\033[2m"; \
	    GREEN = "\033[32m"; YELLOW = "\033[33m"; RESET = "\033[0m"; \
	    printf "\n%s  HDL Template%s\n", BOLD, RESET; \
	  } \
	  /^##@ / { \
	    printf "\n%s  %s%s\n", BOLD, substr($$0, 5), RESET; next; \
	  } \
	  /^[a-zA-Z_%-][a-zA-Z0-9_%-]*:.*## / { \
	    printf "    %s%-22s%s %s\n", CYAN, $$1, RESET, $$2; \
	  } \
	' $(MAKEFILE_LIST)
	@printf "\n\033[1m  Variables\033[0m\n"
	@printf "    \033[33m%-22s\033[0m %s\n" \
	  "FRAMEWORK"       "vunit | cocotb | native      (default: $(FRAMEWORK))" \
	  "SIM"             "ghdl | verilator | icarus    (default: $(SIM))" \
	  "TOPLEVEL_HDL"    "vhdl | sv                    (default: $(TOPLEVEL_HDL))" \
	  "SCHEMATICS"      "0 | 1                        (default: $(SCHEMATICS))" \
	  "IMPL_FAMILY"     "ice40 | ecp5 | machxo2       (default: $(IMPL_FAMILY))" \
	  "IMPL_DEVICE"     "e.g. hx8k, lfe5u-25f         (default: $(IMPL_DEVICE))" \
	  "IMPL_PACKAGE"    "e.g. ct256, CABGA256          (default: $(IMPL_PACKAGE))" \
	  "ICESTUDIO"       "app/binary name               (default: $(ICESTUDIO))" \
	  "NAME"            "<project>  — required for: make init"
	@printf "\n"
