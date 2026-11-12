# =============================================================================
# scripts/mk/help.mk — `make help`
#
# Lists every target carrying a trailing `## description` in any included file
# (awk over $(MAKEFILE_LIST)); `##@ Section` lines start a new group.
# =============================================================================
.PHONY: help

help: ## Show this help
	@awk ' \
	  BEGIN { \
	    FS = ":.*##"; \
	    BOLD = "\033[1m"; CYAN = "\033[36m"; DIM = "\033[2m"; \
	    GREEN = "\033[32m"; YELLOW = "\033[33m"; RESET = "\033[0m"; \
	    printf "\n%s  HDL Template%s\n", BOLD, RESET; \
	  } \
	  /^##@ / { \
	    printf "\n%s  %s%s\n", BOLD, substr($$0, 5), RESET; next; \
	  } \
	  /^[a-zA-Z_%-][a-zA-Z0-9_%-]*:.*## / { \
	    printf "    %s%-22s%s %s\n", CYAN, $$1, RESET, $$2; \
	  } \
	' $(MAKEFILE_LIST)
	@printf "\n\033[1m  Variables\033[0m\n"
	@printf "    \033[33m%-22s\033[0m %s\n" \
	  "FRAMEWORK"       "vunit | cocotb | native      (default: $(FRAMEWORK))" \
	  "SIM"             "ghdl | verilator | icarus    (default: $(SIM))" \
	  "TOPLEVEL_HDL"    "vhdl | sv                    (default: $(TOPLEVEL_HDL))" \
	  "SCHEMATICS"      "0 | 1                        (default: $(SCHEMATICS))" \
	  "NATIVE_SIM"      "nvc | verilator              (default: $(NATIVE_SIM))" \
	  "SYNTH_TOOL"      "yosys                        (default: $(SYNTH_TOOL))" \
	  "IMPL_TOOL"       "nextpnr                      (default: $(IMPL_TOOL))" \
	  "IMPL_FAMILY"     "ice40 | ecp5 | machxo2       (default: $(IMPL_FAMILY))" \
	  "IMPL_DEVICE"     "e.g. 25k, 85k, hx8k          (default: $(IMPL_DEVICE))" \
	  "IMPL_PACKAGE"    "e.g. CABGA256, ct256          (default: $(IMPL_PACKAGE))" \
	  "IMPL_SPEED"      "ECP5 grade 6 | 7 | 8         (default: $(IMPL_SPEED))" \
	  "IMPL_FREQ_MHZ"   "target clock in MHz          (default: $(IMPL_FREQ_MHZ))" \
	  "ICESTUDIO"       "app/binary name               (default: $(ICESTUDIO))" \
	  "NAME"            "<project>  — required for: make init"
	@printf "\n"
