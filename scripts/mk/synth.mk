# =============================================================================
# scripts/mk/synth.mk — synthesis flow
#
# `synth` dispatches to synth-$(SYNTH_TOOL). Backends register in SYNTH_TOOLS
# and live in scripts/mk/tools/ (yosys.mk today; e.g. vivado.mk later).
# =============================================================================
.PHONY: synth synth-gui

##@ Synthesis

SYNTH_TOOL ?= yosys
SYNTH_RDIR  = $(AUTODOC_REPORTS_DIR)/yosys

synth: synth-$(SYNTH_TOOL) ## Synthesise  [SYNTH_TOOL=yosys  TOPLEVEL_HDL=vhdl|sv]
	@:

# Help entry only; the recipe is in scripts/mk/tools/yosys.mk.
synth-gui: synth ## Open Yosys schematic viewer for the last synthesis  [TOPLEVEL_HDL=vhdl|sv]

synth-%:
	$(call unknown-tool,synth,SYNTH_TOOL,$(SYNTH_TOOLS))
