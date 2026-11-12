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

# Top-level module for implementation, pins left unplaced (an area/Fmax measurement, not a
# board design). SV: <<NAME>>_top. VHDL: <<NAME>>_core, because the AXI-Lite records of
# <<NAME>>_top flatten to more IO bits than the default package has pins ("no BELs remaining").
# A design whose ports exceed the package needs a few-pin wrapper: add it under the Bender
# target `impl_sv` (see Bender.yml; SV only) and set IMPL_TOPLEVEL to it.
IMPL_TOPLEVEL ?= $(if $(filter sv,$(HDL_KIND)),<<NAME>>_top,<<NAME>>_core)

# Target clock in MHz. It is passed to nextpnr as --freq and is the figure `make impl` checks
# nextpnr's routed result against, failing the build when it is not met.
IMPL_FREQ_MHZ ?= 200

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
