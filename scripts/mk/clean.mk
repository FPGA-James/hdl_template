# =============================================================================
# scripts/mk/clean.mk — clean targets
# =============================================================================
.PHONY: clean clean-generated clean-all

# =============================================================================
# Clean
# =============================================================================

##@ Clean

clean: ## Remove build outputs (out/) and sim artefacts
	@rm -rf out/docs/ out/vunit/ out/cocotb/ out/native/ out/reports/
	@$(MAKE) -C tb/cocotb clean 2>/dev/null || true

clean-generated: clean ## Remove all generated files (out/regs/, out/synth/, out/impl/, filelist.f)
	@rm -rf out/regs/ out/registers/ out/synth/ out/impl/ filelist.f
	@find . \( -name "*.fst" -o -name "*.vcd" -o -name "*.ghw" -o -name "*.vvp" \) \
	  | xargs rm -f 2>/dev/null || true
	@$(MAKE) --no-print-directory doc-clean-generated

clean-all: clean-generated ## Full reset including .venv/
	@$(MAKE) --no-print-directory doc-clean-all
	@rm -rf __pycache__
	@rm -rf .venv/
