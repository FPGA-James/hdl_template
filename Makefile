# =============================================================================
# HDL Template — Top-Level Makefile
#
# Usage:
#   make venv                         Set up Python virtual environment (once)
#   make init NAME=my_module          Initialise project (replace <<NAME>>)
#   make deps                         Fetch HDL dependencies via Bender
#   make regs                         Generate register files from TOML
#   make sim                          Run simulation (default: vunit + ghdl + vhdl)
#   make sim FRAMEWORK=cocotb SIM=ghdl TOPLEVEL_HDL=vhdl
#   make sim FRAMEWORK=cocotb SIM=verilator TOPLEVEL_HDL=sv
#   make sim FRAMEWORK=cocotb SIM=icarus   TOPLEVEL_HDL=sv
#   make synth                        Synthesise with Yosys (default: VHDL path)
#   make synth TOPLEVEL_HDL=sv        Synthesise SV with Yosys
#   make html                         Build Sphinx documentation
#   make lint                         Run GHDL + vsg (VHDL) and Verilator (SV)
#   make test-autodoc                 Run hdl_autodoc Python test suite
#   make clean                        Remove generated artefacts
# =============================================================================

# ── User-configurable variables ───────────────────────────────────────────────
# Verification framework: vunit | cocotb
FRAMEWORK    ?= vunit

# Simulator: ghdl | verilator | icarus
SIM          ?= ghdl

# HDL language for simulation/synthesis: vhdl | sv
TOPLEVEL_HDL ?= vhdl

# Top-level entity/module name (set by make init; matches <<NAME>>_top)
TOPLEVEL     ?= NAME_top

# Python interpreter — always use the project venv (run `make venv` first)
PYTHON       ?= .venv/bin/python3

# Bender binary (must be on PATH or set here)
BENDER       ?= bender

# Documentation title
PROJECT      ?= $(notdir $(CURDIR))

# Set to 1 to include RTL schematics in docs (requires yosys + ghdl-yosys-plugin)
SCHEMATICS   ?= 0

# ── HDL AutoDoc pipeline variables ───────────────────────────────────────────
AUTODOC_SPHINXBUILD    = $(PYTHON) -m sphinx
AUTODOC_SOURCEDIR      = docs
AUTODOC_BUILDDIR       = docs/_build
AUTODOC_SCRIPTDIR      = scripts/hdl_autodoc
AUTODOC_FILELIST       = filelist.f
AUTODOC_HIERARCHY_JSON = $(AUTODOC_SOURCEDIR)/hierarchy.json

# ── Bender-generated file lists (evaluated lazily) ───────────────────────────
VHDL_RTL  = $(shell $(BENDER) script flist -t rtl_vhdl  --no-default-target 2>/dev/null)
SV_RTL    = $(shell $(BENDER) script flist -t rtl_sv    --no-default-target 2>/dev/null)
VHDL_GEN  = $(shell $(BENDER) script flist -t gen_vhdl  --no-default-target 2>/dev/null)

# =============================================================================
# Phony targets
# =============================================================================
.PHONY: all venv init deps filelist regs \
        sim sim-vunit sim-cocotb \
        synth \
        hierarchy scaffold extract html pdf doc \
        lint lint-vhdl lint-sv \
        test-autodoc \
        clean clean-generated clean-all \
        help

all: regs sim

# =============================================================================
# Guards
# =============================================================================

# check-venv: abort with a clear message if the venv has not been created.
# Call $(call check-venv) at the top of any target that invokes $(PYTHON).
define check-venv
	@test -f .venv/bin/python3 || \
	  (echo "" && \
	   echo "ERROR: Python virtual environment not found." && \
	   echo "       Run 'make venv' first, then retry." && \
	   echo "" && exit 1)
endef

# =============================================================================
# Virtual environment
# =============================================================================

## venv: Create .venv and install all Python dependencies.
##        Run once before any other target that uses Python.
venv:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements.txt
	@echo ""
	@echo "Virtual environment ready. No activation needed — targets use .venv/bin/python3 directly."

## install: Install/upgrade dependencies into the active venv.
install:
	$(call check-venv)
	$(PYTHON) -m pip install --upgrade -r requirements.txt

# =============================================================================
# Project initialisation
# =============================================================================

## init NAME=<name>: Replace all <<NAME>> placeholders and rename files.
##                    Run once after cloning the template.
init:
	@test -n "$(NAME)" || \
	  (echo "ERROR: Specify a project name: make init NAME=my_module" && exit 1)
	bash scripts/init_project.sh $(NAME)

# =============================================================================
# Dependency management
# =============================================================================

## deps: Fetch and vendor all HDL dependencies into deps/ via Bender.
deps:
	$(BENDER) update
	$(BENDER) vendor init

# =============================================================================
# File list (for hdl_autodoc)
# =============================================================================

## filelist: Generate filelist.f from Bender (feeds into hdl_autodoc pipeline).
filelist:
	bash scripts/gen_filelist.sh > $(AUTODOC_FILELIST)

# =============================================================================
# Register generation
# =============================================================================

## regs: Generate VHDL, C header and HTML register files from TOML source.
##        Outputs land in gen/ (gitignored). Run before sim, synth, or html.
regs: gen/vhdl/.stamp

gen/vhdl/.stamp: $(wildcard regs/*.toml) scripts/gen_regs.py
	$(call check-venv)
	@mkdir -p gen/vhdl gen/sv gen/c
	$(PYTHON) scripts/gen_regs.py
	@touch gen/vhdl/.stamp gen/sv/.stamp gen/c/.stamp

# =============================================================================
# Simulation
# =============================================================================

## sim: Run simulation. Respects FRAMEWORK= and SIM= variables.
##       VUnit always uses GHDL (VHDL only).
##       cocotb dispatches to SIM= based on TOPLEVEL_HDL=.
sim: regs
ifeq ($(FRAMEWORK),vunit)
	$(MAKE) sim-vunit
else ifeq ($(FRAMEWORK),cocotb)
	$(MAKE) sim-cocotb
else
	$(error Unknown FRAMEWORK=$(FRAMEWORK). Valid: vunit | cocotb)
endif

## sim-vunit: Run VUnit testbench via GHDL (VHDL only).
sim-vunit: regs
	$(call check-venv)
	VUNIT_SIMULATOR=ghdl $(PYTHON) tb/vunit/run.py $(VUNIT_ARGS)

## sim-vunit-gui: Open VUnit testbench in the GHDL waveform viewer.
sim-vunit-gui: regs
	$(call check-venv)
	VUNIT_SIMULATOR=ghdl $(PYTHON) tb/vunit/run.py --gui $(VUNIT_ARGS)

## sim-cocotb: Run cocotb testbench. Passes SIM= and TOPLEVEL_HDL= to tb/cocotb/Makefile.
sim-cocotb: regs
	$(MAKE) -C tb/cocotb SIM=$(SIM) TOPLEVEL=$(TOPLEVEL) TOPLEVEL_HDL=$(TOPLEVEL_HDL)

# =============================================================================
# Synthesis (Yosys → Xilinx 7-series)
# =============================================================================

## synth: Synthesise with Yosys. Default: VHDL via ghdl-yosys-plugin.
##         Use TOPLEVEL_HDL=sv for the native SystemVerilog path.
synth: regs
	@mkdir -p synth/output
ifeq ($(TOPLEVEL_HDL),sv)
	yosys synth/NAME_sv_xc7.ys
else
	yosys synth/NAME_vhdl_xc7.ys
endif

# =============================================================================
# Documentation (HDL AutoDoc + Sphinx)
# =============================================================================

## hierarchy: Parse filelist.f and write docs/hierarchy.json.
hierarchy: filelist
	$(call check-venv)
	$(PYTHON) $(AUTODOC_SCRIPTDIR)/parse_hierarchy.py \
	  $(AUTODOC_FILELIST) $(AUTODOC_HIERARCHY_JSON)

## scaffold: Generate per-module RST shells (runs hierarchy first).
scaffold: hierarchy
	$(PYTHON) $(AUTODOC_SCRIPTDIR)/generate_rst.py \
	  src $(AUTODOC_SOURCEDIR) "$(PROJECT)"

## extract: Extract FSM, CDC, block and process docs (runs scaffold first).
extract: scaffold
	$(PYTHON) $(AUTODOC_SCRIPTDIR)/run_extract.py \
	  $(AUTODOC_HIERARCHY_JSON) $(AUTODOC_SOURCEDIR) $(AUTODOC_SCRIPTDIR) \
	  $(if $(filter 1,$(SCHEMATICS)),--schematics)
	$(PYTHON) $(AUTODOC_SCRIPTDIR)/generate_rst.py \
	  src $(AUTODOC_SOURCEDIR) "$(PROJECT)"

## html: Build full HTML Sphinx documentation.
html: regs extract
	$(call check-venv)
	@mkdir -p $(AUTODOC_SOURCEDIR)/_static $(AUTODOC_SOURCEDIR)/_templates
	$(PYTHON) $(AUTODOC_SCRIPTDIR)/include_registers.py .
	$(AUTODOC_SPHINXBUILD) -M html $(AUTODOC_SOURCEDIR) $(AUTODOC_BUILDDIR)
	@echo ""
	@echo "Documentation: $(AUTODOC_BUILDDIR)/html/index.html"

## pdf: Build PDF documentation via LaTeX.
pdf: regs extract
	$(call check-venv)
	$(PYTHON) $(AUTODOC_SCRIPTDIR)/include_registers.py .
	$(AUTODOC_SPHINXBUILD) -M latexpdf $(AUTODOC_SOURCEDIR) $(AUTODOC_BUILDDIR)

## doc: Build both HTML and PDF documentation.
doc: html pdf

# =============================================================================
# Linting
# =============================================================================

## lint: Run all linters (VHDL and SV).
lint: lint-vhdl lint-sv

## lint-vhdl: GHDL analysis (type/syntax) + vsg (style guide).
lint-vhdl:
	ghdl -a --std=08 --work=work $(VHDL_RTL) $(VHDL_GEN)
	vsg --configuration vsg.yml --filename $(VHDL_RTL)

## lint-sv: Verilator lint-only pass with all warnings enabled.
lint-sv:
	$(BENDER) script verilator -t rtl_sv 2>/dev/null | \
	  xargs verilator --lint-only --top-module $(TOPLEVEL) -Wall

# =============================================================================
# Test suite (hdl_autodoc Python unit tests)
# =============================================================================

## test-autodoc: Run the scripts/hdl_autodoc/tests/ pytest suite.
test-autodoc:
	$(call check-venv)
	$(PYTHON) -m pytest

# =============================================================================
# Clean
# =============================================================================

## clean: Remove Sphinx build output only.
clean:
	rm -rf $(AUTODOC_BUILDDIR)
	$(MAKE) -C tb/cocotb clean 2>/dev/null || true

## clean-generated: Remove all always-regenerated files (gen/, synth outputs, filelist.f).
clean-generated: clean
	rm -rf gen/ synth/output/ filelist.f waves/
	find . -name "*.fst" -o -name "*.vcd" -o -name "*.ghw" -o -name "*.vvp" \
	  | xargs rm -f 2>/dev/null || true
	rm -f  $(AUTODOC_HIERARCHY_JSON)
	rm -f  $(AUTODOC_SOURCEDIR)/index.rst $(AUTODOC_SOURCEDIR)/overview.rst
	rm -f  $(AUTODOC_SOURCEDIR)/hierarchy.rst $(AUTODOC_SOURCEDIR)/hierarchy.dot
	rm -f  $(AUTODOC_SOURCEDIR)/registers.rst
	rm -rf $(AUTODOC_SOURCEDIR)/_static/registers
	@if [ -d $(AUTODOC_SOURCEDIR)/modules ]; then \
	  find $(AUTODOC_SOURCEDIR)/modules -maxdepth 2 \
	    -name "index.rst" -o -name "fsm.rst" -o -name "timing.rst" \
	    -o -name "cdc.rst" -o -name "*_cdc.rst" -o -name "*_cdc.dot" \
	    -o -name "block.rst" -o -name "*_block.rst" -o -name "*_block.dot" \
	    -o -name "*_schematic.svg" \
	    -o -name "reset.rst" -o -name "*_reset.rst" -o -name "*_reset.dot" \
	    -o -name "*.dot" -o -name "*.rst" -path "*/processes/*" \
	  | xargs rm -f 2>/dev/null; \
	  find $(AUTODOC_SOURCEDIR)/modules -maxdepth 2 -name "processes" -type d \
	  | xargs rm -rf 2>/dev/null; \
	fi

## clean-all: Remove everything including hand-editable RST shells.
clean-all: clean-generated
	rm -rf $(AUTODOC_SOURCEDIR)/modules __pycache__ sim_build/
	rm -rf .venv/ deps/

# =============================================================================
# Help
# =============================================================================

## help: Print all documented targets.
help:
	@echo ""
	@echo "HDL Template — available targets:"
	@echo ""
	@grep -E '^## ' Makefile | sed 's/^## /  make /'
	@echo ""
	@echo "Key variables:"
	@echo "  FRAMEWORK=vunit|cocotb   (default: vunit)"
	@echo "  SIM=ghdl|verilator|icarus  (default: ghdl)"
	@echo "  TOPLEVEL_HDL=vhdl|sv     (default: vhdl)"
	@echo "  NAME=<project>           (required for: make init)"
	@echo ""
