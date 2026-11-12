# =============================================================================
# scripts/mk/tools/ghdl.mk — GHDL + vsg: VHDL lint
# =============================================================================
.PHONY: lint-vhdl

lint-vhdl: regs
	$(call check-venv)
	@printf "\n\033[1m  Linting VHDL...\033[0m\n\n"
	$(call compile-ghdl-libs,out/synth/workdir)
	@$(OSS_CAD_SUITE)/bin/ghdl -a --std=08 --work=work --workdir=out/synth/workdir -Pout/synth/workdir $(VHDL_GEN) $(VHDL_RTL)
	@# vsg's __main__.py defines main() but never calls it, so `python -m vsg` is a
	@# silent no-op -- call main() explicitly.
	@$(PYTHON) -c 'import sys; from vsg.__main__ import main; sys.exit(main())' --configuration vsg.yml --filename $(VHDL_RTL)
	@printf "\n\033[32m  ✓\033[0m VHDL lint passed\n\n"
