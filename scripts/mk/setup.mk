# =============================================================================
# scripts/mk/setup.mk — environment bring-up and register generation
# =============================================================================
.PHONY: venv install init vars lsp vhdl-ls verible-ls deps regs

# =============================================================================
# Setup
# =============================================================================

##@ Setup

venv: ## Create .venv and install all Python deps (run once)
	@printf "\n\033[1m  Setting up Python virtual environment...\033[0m\n\n"
	@$(SYSTEM_PYTHON3) -m venv .venv
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
	  "NATIVE_SIM"       "$(NATIVE_SIM)" \
	  "SYNTH_TOOL"       "$(SYNTH_TOOL)" \
	  "IMPL_TOOL"        "$(IMPL_TOOL)" \
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
	@# Bridge for the docs pipeline: run_extract.py looks for regs_<module>.toml (keyed by the
	@# owning module <name>_top, not hdl_registers' <name>_regs.toml) in $(AUTODOC_REGISTERS_DIR)
	@# and builds each module's register page from it; generate_rst.py then writes the
	@# "Register Maps" index. Copy the TOMLs there under the expected name.
	@mkdir -p $(AUTODOC_REGISTERS_DIR)
	@for f in regs/*.toml; do \
		n=$$(basename "$$f" _regs.toml); \
		cp "$$f" "$(AUTODOC_REGISTERS_DIR)/regs_$${n}_top.toml"; \
	done
	@touch out/regs/vhdl/.stamp
	@printf "\n\033[32m  ✓\033[0m Registers generated in out/regs/\n\n"

