// =============================================================================
// Company      : <company>
//
// Designer     : <name>
//
// Filename     : <<NAME>>_top_cocotb_top.sv
//
// Purpose      : Flat-port cocotb top level around <<NAME>>_top, whose AXI4-Lite
//                port is an axil_if interface.
//
// Tools        : Verilator + cocotb
//
// References   :
//   - tb/cocotb/Makefile, tb/cocotb/test_NAME.py
//
// Date Created : YYYY-MM-DD
//
// Date Updated : YYYY-MM-DD
// =============================================================================
//
// Revision History
// =============================================================================
// Date        Author          Description
// ----------  --------------  --------------------------------------------
// YYYY-MM-DD  <name>          Initial creation
// =============================================================================

// <<NAME>>_top_cocotb_top.
//
// <<NAME>>_top's s_axil port is typed with an axil_if modport. Neither Verilator
// nor Icarus accepts an interface-typed port on the simulation's top level (and
// Icarus cannot parse interface/modport ports anywhere), so this wrapper gives
// cocotb a flat-port top level and instantiates <<NAME>>_top, unmodified, inside it.
// It plays the same role for SV that <<NAME>>_cocotb_top.vhd plays for VHDL's
// record-typed AXI-Lite ports under GHDL.
//
// Flat port names (s_axi_*) are identical to the VHDL wrapper's, so the same
// cocotbext-axi AxiLiteBus.from_prefix(dut, "s_axi") works for both languages.
// ADDR_W=8/DATA_W=32 match axil_if's defaults. A register map needing more than 8 address
// bits (over 64 registers) needs a larger ADDR_W here, in tb/cpp/NAME_top_cpp_flat.sv and in
// tb/native/sv/NAME_tb.sv, and wider s_axi_*addr ports.
module <<NAME>>_top_cocotb_top (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        pulse_i,

    input  logic [7:0]  s_axi_awaddr,
    input  logic [2:0]  s_axi_awprot,
    input  logic        s_axi_awvalid,
    output logic        s_axi_awready,
    input  logic [31:0] s_axi_wdata,
    input  logic [3:0]  s_axi_wstrb,
    input  logic        s_axi_wvalid,
    output logic        s_axi_wready,
    output logic [1:0]  s_axi_bresp,
    output logic        s_axi_bvalid,
    input  logic        s_axi_bready,
    input  logic [7:0]  s_axi_araddr,
    input  logic [2:0]  s_axi_arprot,
    input  logic        s_axi_arvalid,
    output logic        s_axi_arready,
    output logic [31:0] s_axi_rdata,
    output logic [1:0]  s_axi_rresp,
    output logic        s_axi_rvalid,
    input  logic        s_axi_rready
);

    axil_if #(.ADDR_W(8), .DATA_W(32)) s_axil ();

    assign s_axil.awaddr  = s_axi_awaddr;
    assign s_axil.awprot  = s_axi_awprot;
    assign s_axil.awvalid = s_axi_awvalid;
    assign s_axi_awready  = s_axil.awready;
    assign s_axil.wdata   = s_axi_wdata;
    assign s_axil.wstrb   = s_axi_wstrb;
    assign s_axil.wvalid  = s_axi_wvalid;
    assign s_axi_wready   = s_axil.wready;
    assign s_axi_bresp    = s_axil.bresp;
    assign s_axi_bvalid   = s_axil.bvalid;
    assign s_axil.bready  = s_axi_bready;
    assign s_axil.araddr  = s_axi_araddr;
    assign s_axil.arprot  = s_axi_arprot;
    assign s_axil.arvalid = s_axi_arvalid;
    assign s_axi_arready  = s_axil.arready;
    assign s_axi_rdata    = s_axil.rdata;
    assign s_axi_rresp    = s_axil.rresp;
    assign s_axi_rvalid   = s_axil.rvalid;
    assign s_axil.rready  = s_axi_rready;

    <<NAME>>_top u_<<NAME>>_top (
        .clk     (clk),
        .rst_n   (rst_n),
        .pulse_i (pulse_i),
        .s_axil  (s_axil.slave)
    );

endmodule : <<NAME>>_top_cocotb_top
