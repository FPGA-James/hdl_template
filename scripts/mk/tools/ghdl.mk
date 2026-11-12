# =============================================================================
# scripts/mk/tools/ghdl.mk — GHDL + vsg: VHDL lint
# =============================================================================
.PHONY: lint-vhdl

lint-vhdl: regs
	$(call check-venv)
	@printf "\n\033[1m  Linting VHDL...\033[0m\n\n"
	$(call compile-ghdl-libs,out/synth/workdir)
	@$(OSS_CAD_SUITE)/bin/ghdl -a --std=08 --work=work -Pout/synth/workdir $(VHDL_GEN) $(VHDL_RTL)
	@$(PYTHON) -m vsg --configuration vsg.yml --filename $(VHDL_RTL)
	@printf "\n\033[32m  ✓\033[0m VHDL lint passed\n\n"
