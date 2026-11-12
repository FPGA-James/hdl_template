# =============================================================================
# scripts/mk/tools/nextpnr/nextpnr.mk — open-source implementation: Yosys mapping + nextpnr + packer
#
# Uses the Yosys front end from scripts/mk/tools/yosys/yosys.mk to map the design to the
# target family, then nextpnr-<family> and the family's bitstream packer.
# =============================================================================
IMPL_TOOLS += nextpnr
.PHONY: impl-nextpnr impl-gui-nextpnr impl-nextpnr-synth

# FPGA family for nextpnr.  Determines the synth command, nextpnr binary,
# constraint file format, and bitstream packer.
#   ice40   → nextpnr-ice40  + icepack   (constraint: .pcf)
#   ecp5    → nextpnr-ecp5   + ecppack   (constraint: .lpf)
#   machxo2 → nextpnr-machxo2 + ddtcmd  (constraint: .lpf)
IMPL_FAMILY     ?= ecp5

# Device and package — must match your physical FPGA.
# Defaults follow IMPL_FAMILY: ecp5 -> 25k / CABGA256 / speed 8 (LFE5U-25F, fastest grade),
# ice40 -> hx8k / ct256 (other ice40 parts: IMPL_DEVICE=hx1k IMPL_PACKAGE=tq144).
# machxo2 has no default: pass IMPL_DEVICE and IMPL_PACKAGE.
IMPL_DEVICE_ecp5    = 25k
IMPL_PACKAGE_ecp5   = CABGA256
IMPL_DEVICE_ice40   = hx8k
IMPL_PACKAGE_ice40  = ct256
IMPL_DEVICE     ?= $(IMPL_DEVICE_$(IMPL_FAMILY))
IMPL_PACKAGE    ?= $(IMPL_PACKAGE_$(IMPL_FAMILY))
# ECP5 speed grade (6, 7 or 8; 8 is the fastest). Ignored for other families.
IMPL_SPEED      ?= 8

# Constraint file (.pcf for ice40, .lpf for ecp5/machxo2); optional, see IMPL_PNR_CONSTRAINT_* below.
IMPL_CONSTRAINT ?= synth/constraints/$(IMPL_TOPLEVEL).$(if $(filter ecp5 machxo2,$(IMPL_FAMILY)),lpf,pcf)

IMPL_STEM = $(IMPL_TOPLEVEL)_$(IMPL_FAMILY)

# Per-family nextpnr/packer settings. ecp5 and machxo2 share everything but the
# nextpnr binary (nextpnr-$(IMPL_FAMILY)) and the bitstream packer.
IMPL_CFG                   = out/impl/$(IMPL_TOPLEVEL).$(if $(filter ice40,$(IMPL_FAMILY)),asc,config)
IMPL_BIT                   = out/impl/$(IMPL_TOPLEVEL).bit
# The constraint file is optional: a top without one (e.g. IMPL_TOPLEVEL=<module>) has its pins
# placed automatically, which is all an area/Fmax measurement needs.
IMPL_PNR_CONSTRAINT_ice40   = $(if $(wildcard $(IMPL_CONSTRAINT)),--pcf "$(IMPL_CONSTRAINT)") --pcf-allow-unconstrained
IMPL_PNR_CONSTRAINT_ecp5    = $(if $(wildcard $(IMPL_CONSTRAINT)),--lpf "$(IMPL_CONSTRAINT)") --lpf-allow-unconstrained --speed $(IMPL_SPEED)
IMPL_PNR_CONSTRAINT_machxo2 = $(if $(wildcard $(IMPL_CONSTRAINT)),--lpf "$(IMPL_CONSTRAINT)")
IMPL_PNR_OUT_ice40          = --asc "$(IMPL_CFG)"
IMPL_PNR_OUT_ecp5           = --textcfg "$(IMPL_CFG)"
IMPL_PNR_OUT_machxo2        = --textcfg "$(IMPL_CFG)"
IMPL_PACK_ice40             = $(OSS_CAD_SUITE)/bin/icepack "$(IMPL_CFG)" "$(IMPL_BIT)"
IMPL_PACK_ecp5              = $(OSS_CAD_SUITE)/bin/ecppack --compress "$(IMPL_CFG)" "$(IMPL_BIT)"
IMPL_PACK_machxo2           = $(OSS_CAD_SUITE)/bin/ddtcmd -oft -bit -if "$(IMPL_CFG)" -of "$(IMPL_BIT)"
# --timing-allow-fail: nextpnr would otherwise abort when the target frequency is missed and
# leave no bitstream or report; scripts/check_nextpnr_timing.sh gives the pass/fail verdict instead.
# IMPL_PNR_OPT: placer/router effort. A higher timing weight and timing-driven rip-up gain
# about 5-10% Fmax on this design (results still vary by seed; IMPL_PNR_OPT= turns them off).
IMPL_PNR_OPT               ?= --placer-heap-timingweight 40 --tmg-ripup
IMPL_PNR_ARGS               = -q --timing-allow-fail --freq $(IMPL_FREQ_MHZ) $(IMPL_PNR_OPT) --$(IMPL_DEVICE) --package $(IMPL_PACKAGE) \
                              --json "out/impl/$(IMPL_STEM).json" $(IMPL_PNR_CONSTRAINT_$(IMPL_FAMILY))

# impl-nextpnr-synth — map the design to the target family (shared by impl and impl-gui).
impl-nextpnr-synth: YOSYS_TOP = $(IMPL_TOPLEVEL)
impl-nextpnr-synth: YOSYS_EXTRA_SRC = $(SV_IMPL)
# TARGET_ECP5 / TARGET_ICE40 / TARGET_MACHXO2: lets RTL pick a family primitive
# (e.g. to instantiate a block-RAM primitive under `ifdef TARGET_ECP5).
impl-nextpnr-synth: YOSYS_DEFINES = -DTARGET_$(shell echo $(IMPL_FAMILY) | tr a-z A-Z)
impl-nextpnr-synth: regs
	$(if $(IMPL_PACK_$(IMPL_FAMILY)),,$(error Unknown IMPL_FAMILY=$(IMPL_FAMILY). Valid: ice40 | ecp5 | machxo2))
	@mkdir -p out/impl $(IMPL_RDIR) $(AUTODOC_REPORTS_DIR)/yosys
	$(yosys-prep)
	@printf "\n\033[1m  Synthesising $(IMPL_TOPLEVEL) for $(IMPL_FAMILY) ($(IMPL_DEVICE)/$(IMPL_PACKAGE))...\033[0m\n\n"
	@$(OSS_CAD_SUITE)/bin/yosys -q \
	  -l "$(AUTODOC_REPORTS_DIR)/yosys/yosys.log" \
	  $(YOSYS_READ_$(HDL_KIND)) \
	  -p "synth_$(IMPL_FAMILY) -top $(IMPL_TOPLEVEL) -json out/impl/$(IMPL_STEM).json" \
	  -p "tee -o $(AUTODOC_REPORTS_DIR)/yosys/stat.txt stat"

impl-nextpnr: impl-nextpnr-synth
	@printf "  \033[2m[nextpnr]\033[0m Place and route...\n"
	@$(OSS_CAD_SUITE)/bin/nextpnr-$(IMPL_FAMILY) $(IMPL_PNR_ARGS) \
	  $(IMPL_PNR_OUT_$(IMPL_FAMILY)) \
	  --write  "$(IMPL_RDIR)/$(IMPL_STEM)_routed.json" \
	  --report "$(IMPL_RDIR)/$(IMPL_STEM)_timing.json" \
	  --detailed-timing-report \
	  --sdf    "$(IMPL_RDIR)/$(IMPL_STEM)_routed.sdf" \
	  --placed-svg "$(IMPL_RDIR)/$(IMPL_STEM)_placed.svg" \
	  --routed-svg "$(IMPL_RDIR)/$(IMPL_STEM)_routed.svg" \
	  -l       "$(AUTODOC_REPORTS_DIR)/yosys/nextpnr.log"
	@printf "  \033[2m[pack]\033[0m Packing bitstream...\n"
	@$(IMPL_PACK_$(IMPL_FAMILY))
	@printf "\n\033[32m  ✓\033[0m Bitstream: \033[36m$(IMPL_BIT)\033[0m\n"
	@printf "    Reports: \033[36m$(IMPL_RDIR)/$(IMPL_STEM)_*\033[0m, \033[36m$(AUTODOC_REPORTS_DIR)/yosys/nextpnr.log\033[0m\n\n"
	@printf "  \033[2m[timing]\033[0m Target $(IMPL_FREQ_MHZ) MHz:\n"
	@bash scripts/check_nextpnr_timing.sh "$(AUTODOC_REPORTS_DIR)/yosys/nextpnr.log" $(IMPL_FREQ_MHZ)

impl-gui-nextpnr: impl-nextpnr-synth
	@printf "  \033[2m[nextpnr]\033[0m Opening GUI...\n\n"
	@$(OSS_CAD_SUITE)/bin/nextpnr-$(IMPL_FAMILY) --gui $(filter-out -q,$(IMPL_PNR_ARGS))
