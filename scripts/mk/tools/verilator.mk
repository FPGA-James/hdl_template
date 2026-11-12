# =============================================================================
# scripts/mk/tools/verilator.mk — Verilator: native SV bench, C++ bench, SV lint
# =============================================================================
SIM_NATIVE_TOOLS += verilator
.PHONY: sim-native-verilator sim-cpp lint-sv

# RTL (and generated register file) for the Verilator-based native/C++ benches.
SV_SIM_SRC = $(SV_GEN) $(SV_RTL)

sim-native-verilator: regs
	@printf "\n\033[1m  Running native SystemVerilog simulation (Verilator)...\033[0m\n\n"
	@mkdir -p $(NATIVE_RDIR)/verilator_obj
	@$(OSS_CAD_SUITE)/bin/verilator --binary --timing -Wall -Wno-fatal -j 0 -Isrc \
	  -Mdir $(NATIVE_RDIR)/verilator_obj --top-module <<NAME>>_tb \
	  tb/native/sv/axi_lite_driver_pkg.sv \
	  $(SV_SIM_SRC) \
	  tb/native/sv/<<NAME>>_tb.sv
	@$(NATIVE_RDIR)/verilator_obj/V<<NAME>>_tb
	@printf "\n\033[32m  ✓\033[0m Native SystemVerilog simulation passed\n\n"

sim-cpp: regs
ifneq ($(TOPLEVEL_HDL),sv)
	$(error sim-cpp requires TOPLEVEL_HDL=sv -- Verilator does not read VHDL)
endif
	@printf "\n\033[1m  Running C++ testbench (Verilator --cc --exe --build)...\033[0m\n\n"
	@mkdir -p $(NATIVE_RDIR)/cpp_obj
	@$(OSS_CAD_SUITE)/bin/verilator --cc --exe --build -Wall -Wno-fatal -j 0 -Isrc \
	  -Mdir $(NATIVE_RDIR)/cpp_obj --top-module <<NAME>>_top_cpp_flat \
	  $(SV_SIM_SRC) \
	  tb/cpp/<<NAME>>_top_cpp_flat.sv \
	  tb/cpp/<<NAME>>_tb.cpp \
	  -CFLAGS "-I$(CURDIR)/tb/cpp -I$(CURDIR)/out/regs/c" \
	  -o <<NAME>>_tb_cpp
	@$(NATIVE_RDIR)/cpp_obj/<<NAME>>_tb_cpp
	@printf "\n\033[32m  ✓\033[0m C++ testbench passed\n\n"

lint-sv: regs
	@printf "\n\033[1m  Linting SystemVerilog...\033[0m\n\n"
	@$(BENDER) script verilator -t rtl_sv -t gen_sv 2>/dev/null | \
	  xargs $(OSS_CAD_SUITE)/bin/verilator --lint-only --top-module "$(TOPLEVEL)" -Wall -Wno-fatal -Werror-WIDTHTRUNC -Isrc
	@printf "\n\033[32m  ✓\033[0m SV lint passed\n\n"
