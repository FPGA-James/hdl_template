// Flattening wrapper for the C++ testbench (tb/cpp/<<NAME>>_tb.cpp). Verilator
// does not support interface-typed ports on its top-level module
// ("%Error-UNSUPPORTED: Interfaced port on top level module"), so <<NAME>>_top
// itself cannot be passed to --top-module while it has an axil_if port. This
// wrapper gives it a plain-port top module to elaborate instead, mirrors
// tb/cocotb/<<NAME>>_top_cocotb_top.sv, instantiates the real <<NAME>>_top
// unmodified, and re-exposes the flat s_axi_* port names so that
// tb/cpp/axi_lite_driver.hpp needs no interface knowledge.
//
// LANDMINE: do not let any comment LINE in this file begin with the tool's
// own name (case-sensitive, first non-whitespace word) -- its comment scanner
// misparses that as a pragma directive (%Error-BADVLTPRAGMA).
module <<NAME>>_top_cpp_flat (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        pulse_i,

    output logic        s_axi_awready,
    input  logic        s_axi_awvalid,
    input  logic [7:0]  s_axi_awaddr,
    output logic        s_axi_wready,
    input  logic        s_axi_wvalid,
    input  logic [31:0] s_axi_wdata,
    input  logic [3:0]  s_axi_wstrb,
    input  logic        s_axi_bready,
    output logic        s_axi_bvalid,
    output logic [1:0]  s_axi_bresp,
    output logic        s_axi_arready,
    input  logic        s_axi_arvalid,
    input  logic [7:0]  s_axi_araddr,
    input  logic        s_axi_rready,
    output logic        s_axi_rvalid,
    output logic [31:0] s_axi_rdata,
    output logic [1:0]  s_axi_rresp
);

    axil_if #(.ADDR_W(8), .DATA_W(32)) s_axil ();

    assign s_axil.awvalid = s_axi_awvalid;
    assign s_axil.awaddr  = s_axi_awaddr;
    assign s_axil.awprot  = 3'b000;
    assign s_axi_awready  = s_axil.awready;

    assign s_axil.wvalid  = s_axi_wvalid;
    assign s_axil.wdata   = s_axi_wdata;
    assign s_axil.wstrb   = s_axi_wstrb;
    assign s_axi_wready   = s_axil.wready;

    assign s_axil.bready  = s_axi_bready;
    assign s_axi_bvalid   = s_axil.bvalid;
    assign s_axi_bresp    = s_axil.bresp;

    assign s_axil.arvalid = s_axi_arvalid;
    assign s_axil.araddr  = s_axi_araddr;
    assign s_axil.arprot  = 3'b000;
    assign s_axi_arready  = s_axil.arready;

    assign s_axil.rready  = s_axi_rready;
    assign s_axi_rvalid   = s_axil.rvalid;
    assign s_axi_rdata    = s_axil.rdata;
    assign s_axi_rresp    = s_axil.rresp;

    <<NAME>>_top u_dut (
        .clk(clk), .rst_n(rst_n), .pulse_i(pulse_i),
        .s_axil(s_axil.slave)
    );

endmodule : <<NAME>>_top_cpp_flat
