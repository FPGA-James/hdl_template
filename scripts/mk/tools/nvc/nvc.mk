# =============================================================================
# scripts/mk/tools/nvc/nvc.mk — NVC: native (framework-less) VHDL simulation
# =============================================================================
SIM_NATIVE_TOOLS += nvc
.PHONY: sim-native-nvc

# NVC binary. Not part of OSS CAD Suite; install separately
# (e.g. `brew install nvc` or https://www.nickg.me.uk/nvc/).
NVC ?= nvc

NATIVE_NVC_LIBDIR = $(NATIVE_RDIR)/nvc_libs

# check-nvc — abort with a clear message if NVC is not on PATH.
define check-nvc
	@command -v $(NVC) >/dev/null 2>&1 || \
	  (printf "\n\033[1;31m  ERROR:\033[0m NVC not found (checked '\033[36m$(NVC)\033[0m').\n" && \
	   printf  "         Install NVC (e.g. '\033[36mbrew install nvc\033[0m' or https://www.nickg.me.uk/nvc/)\n" && \
	   printf  "         or override the binary path: \033[36mmake sim-native NVC=/path/to/nvc\033[0m\n\n" && \
	   exit 1)
endef

sim-native-nvc: regs
	$(call check-nvc)
	@printf "\n\033[1m  Running native VHDL simulation (NVC)...\033[0m\n\n"
	@mkdir -p $(NATIVE_NVC_LIBDIR) $(NATIVE_RDIR)/nvc_work
	@printf "  \033[2m[nvc]\033[0m Compiling axi_lite library...\n"
	@$(NVC) --std=2008 --work=axi_lite:$(NATIVE_NVC_LIBDIR)/axi_lite -a \
	  $(VHDL_AXI_LITE)
	@printf "  \033[2m[nvc]\033[0m Compiling register_file library...\n"
	@$(NVC) --std=2008 --work=register_file:$(NATIVE_NVC_LIBDIR)/register_file \
	  -L $(NATIVE_NVC_LIBDIR) -a $(VHDL_REG_FILE)
	@$(NVC) --std=2008 --work=$(NATIVE_RDIR)/nvc_work -L $(NATIVE_NVC_LIBDIR) -a \
	  $(VHDL_GEN) $(VHDL_RTL) tb/native/vhdl/<<NAME>>_tb.vhd
	@$(NVC) --work=$(NATIVE_RDIR)/nvc_work -L $(NATIVE_NVC_LIBDIR) -e <<NAME>>_tb
	@$(NVC) --work=$(NATIVE_RDIR)/nvc_work -L $(NATIVE_NVC_LIBDIR) -r <<NAME>>_tb
	@printf "\n\033[32m  ✓\033[0m Native VHDL simulation passed\n\n"
