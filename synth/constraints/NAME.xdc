# <<NAME>> XDC constraints template for Xilinx 7-series.
#
# Used by Vivado after Yosys produces the EDIF netlist.
# Customise pin assignments and timing for your target board.
#
# Example target: Arty A7-35T (xc7a35tcpg236-1)

# ── Clock ─────────────────────────────────────────────────────────────────────
# 100 MHz system clock on Arty A7 (E3 → gclk)
create_clock -period 10.000 -name clk [get_ports clk]

# ── Resets ────────────────────────────────────────────────────────────────────
set_false_path -from [get_ports rst_n]

# ── AXI-Lite register bus timing ──────────────────────────────────────────────
# Relax AXI bus timing if driven from a lower-speed domain.
# set_max_delay -datapath_only 20.000 -from [get_ports s_axi_*]

# ── I/O Pin assignments (Arty A7-35T example) ─────────────────────────────────
# Update to match your board pinout.
set_property PACKAGE_PIN E3  [get_ports clk]
set_property IOSTANDARD  LVCMOS33 [get_ports clk]

set_property PACKAGE_PIN C2  [get_ports rst_n]
set_property IOSTANDARD  LVCMOS33 [get_ports rst_n]

set_property PACKAGE_PIN A8  [get_ports pulse_i]
set_property IOSTANDARD  LVCMOS33 [get_ports pulse_i]
