# =============================================================================
# scripts/mk/impl.mk — place-and-route / bitstream flow
#
# `impl` and `impl-gui` dispatch to impl-$(IMPL_TOOL) / impl-gui-$(IMPL_TOOL).
# Backends register in IMPL_TOOLS (nextpnr.mk today; e.g. vivado.mk later) and
# own their device variables (family/part/package/constraint).
# =============================================================================
.PHONY: impl impl-gui icestudio

##@ Implementation

IMPL_TOOL ?= nextpnr

# Top-level module for implementation. The default places <<NAME>>_top with its
# pins left unconstrained (synth/constraints/<top>.lpf), which gives area and Fmax.
# A design whose port bits exceed the package's pins needs a wrapper with few pins:
# add it under the Bender target `impl_sv` (see Bender.yml) and set IMPL_TOPLEVEL.
IMPL_TOPLEVEL ?= <<NAME>>_top

# Target clock in MHz. It is the FREQUENCY in the constraint file
# (synth/constraints/<top>.lpf) and the figure `make impl` checks nextpnr's routed
# result against, failing the build when it is not met.
IMPL_FREQ_MHZ ?= 250

IMPL_RDIR = $(AUTODOC_REPORTS_DIR)/impl

impl: impl-$(IMPL_TOOL) ## Place-and-route  [IMPL_TOOL=nextpnr  IMPL_FAMILY=ice40|ecp5|machxo2  IMPL_DEVICE=  IMPL_PACKAGE=  TOPLEVEL_HDL=vhdl|sv]
	@:

impl-gui: impl-gui-$(IMPL_TOOL) ## Open the interactive placement/routing GUI  [IMPL_TOOL=nextpnr  IMPL_FAMILY=ice40|ecp5|machxo2  TOPLEVEL_HDL=vhdl|sv]
	@:

# Help entry only; the recipe is in scripts/mk/tools/icestudio.mk.
icestudio: impl ## Run full impl then open IceStudio for device programming

impl-gui-%:
	$(call unknown-tool,impl-gui,IMPL_TOOL,$(IMPL_TOOLS))

impl-%:
	$(call unknown-tool,impl,IMPL_TOOL,$(IMPL_TOOLS))
