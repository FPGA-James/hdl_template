# =============================================================================
# scripts/mk/lint.mk — linting and tests
#
# `lint` lints the active language. The per-language linters live with their
# tool: lint-vhdl in scripts/mk/tools/ghdl/ghdl.mk, lint-sv in scripts/mk/tools/verilator/verilator.mk.
# =============================================================================
.PHONY: lint lint-vhdl lint-sv test-autodoc

##@ Linting

lint: lint-$(HDL_KIND) ## Lint the active language  [TOPLEVEL_HDL=vhdl|sv]
	@:

# Help entries only; the recipes are in the tool files.
lint-vhdl: ## GHDL analysis (type/syntax) + vsg style guide
lint-sv: ## Verilator lint-only pass with all warnings enabled

# =============================================================================
# Testing
# =============================================================================

##@ Testing

test-autodoc: ## Run the HDL AutoDoc submodule's pytest suite
	$(call check-venv)
	$(call check-submodule)
	@printf "\n\033[1m  Running HDL AutoDoc tests...\033[0m\n\n"
	@$(SPHINX_ENV) $(PYTHON) -m pytest
