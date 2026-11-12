# =============================================================================
# scripts/mk/tools/yosys.mk — Yosys: synthesis (Xilinx 7-series), shared front end
#
# The YOSYS_READ_* / yosys-prep pieces are also used by the nextpnr
# implementation flow (scripts/mk/tools/nextpnr.mk) to map the design to a target.
# =============================================================================
SYNTH_TOOLS += yosys
.PHONY: synth-yosys synth-gui

# Yosys front end per language. YOSYS_TOP is the unit the VHDL front end
# elaborates; synth-yosys sets it to TOPLEVEL, the nextpnr flow to IMPL_TOPLEVEL.
# YOSYS_EXTRA_SRC: extra files for one flow (the implementation top for the nextpnr flow).
# YOSYS_DEFINES: extra read_verilog -D options for one flow (the nextpnr flow sets TARGET_<FAMILY>).
YOSYS_READ_sv   = -p "read_verilog -sv $(YOSYS_DEFINES) $(SV_GEN) $(SV_RTL) $(YOSYS_EXTRA_SRC)"
YOSYS_READ_vhdl = -p "plugin -i ghdl" \
                  -p "ghdl --std=08 -Pout/synth/workdir $(VHDL_RTL) $(VHDL_GEN) -e $(YOSYS_TOP)"
LANG_NAME_sv    = SystemVerilog
LANG_NAME_vhdl  = VHDL

# yosys-prep — abort on an empty Bender source list; VHDL additionally needs
# hdl-modules compiled into named GHDL libraries first.
define yosys-prep
	$(if $(filter sv,$(HDL_KIND)),$(call check-rtl-list,$(SV_RTL),SV_RTL),$(call check-rtl-list,$(VHDL_RTL),VHDL_RTL))
	$(if $(filter vhdl,$(HDL_KIND)),$(call compile-ghdl-libs,out/synth/workdir))
endef

synth-yosys: YOSYS_TOP = $(TOPLEVEL)
synth-yosys: regs
	@mkdir -p out/synth $(SYNTH_RDIR)
	$(yosys-prep)
	@printf "\n\033[1m  Synthesising $(TOPLEVEL) ($(LANG_NAME_$(HDL_KIND)) → Xilinx xc7)...\033[0m\n\n"
	@$(OSS_CAD_SUITE)/bin/yosys -q \
	  -l "$(SYNTH_RDIR)/yosys.log" \
	  $(YOSYS_READ_$(HDL_KIND)) \
	  -p "synth_xilinx -family xc7 -top $(TOPLEVEL) -edif out/synth/$(TOPLEVEL)_$(HDL_KIND).edif" \
	  -p "tee -o $(SYNTH_RDIR)/check.txt check" \
	  -p "tee -o $(SYNTH_RDIR)/stat.txt stat -tech xilinx" \
	  -p "write_json $(SYNTH_RDIR)/netlist.json"
	@printf "\n\033[32m  ✓\033[0m Netlist:  \033[36mout/synth/$(TOPLEVEL)_$(HDL_KIND).edif\033[0m\n"
	@printf "    Reports: \033[36m$(SYNTH_RDIR)/\033[0m (yosys.log stat.txt check.txt netlist.json)\n\n"

# Opens the JSON netlist written by synth-yosys (the target is declared in scripts/mk/synth.mk).
synth-gui:
	@printf "\n\033[1m  Opening Yosys schematic viewer...\033[0m\n\n"
	@$(OSS_CAD_SUITE)/bin/yosys \
	  -p "read_json $(SYNTH_RDIR)/netlist.json; show $(TOPLEVEL)"
