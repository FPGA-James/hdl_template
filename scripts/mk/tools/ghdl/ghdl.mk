# =============================================================================
# scripts/mk/tools/ghdl/ghdl.mk — GHDL + vsg: VHDL lint
#
# Reports: ghdl/lint.log (GHDL analysis) and vsg/ -- vsg.log, vsg.json, vsg.xml (JUnit) and
# code_quality.json (GitLab code-quality format).
# =============================================================================
.PHONY: lint-vhdl

GHDL_RDIR = $(AUTODOC_REPORTS_DIR)/ghdl
VSG_RDIR  = $(AUTODOC_REPORTS_DIR)/vsg

lint-vhdl: regs
	$(call check-venv)
	@printf "\n\033[1m  Linting VHDL...\033[0m\n\n"
	$(call compile-ghdl-libs,out/synth/workdir)
	$(call run-logged,$(GHDL_RDIR)/lint.log,$(OSS_CAD_SUITE)/bin/ghdl -a --std=08 --work=work --workdir=out/synth/workdir -Pout/synth/workdir $(VHDL_GEN) $(VHDL_RTL))
	@# vsg's __main__.py defines main() but never calls it, so `python -m vsg` is a
	@# silent no-op -- call main() explicitly.
	$(call run-logged,$(VSG_RDIR)/vsg.log,$(PYTHON) -c 'import sys; from vsg.__main__ import main; sys.exit(main())' --configuration vsg.yml \
	  --json $(VSG_RDIR)/vsg.json --junit $(VSG_RDIR)/vsg.xml --quality_report $(VSG_RDIR)/code_quality.json --filename $(VHDL_RTL))
	@printf "\n\033[32m  ✓\033[0m VHDL lint passed\n\n"
