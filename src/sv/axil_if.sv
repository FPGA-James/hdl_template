// =============================================================================
// Company      : <company>
//
// Designer     : <name>
//
// Filename     : axil_if.sv
//
// Purpose      : AXI4-Lite interface bundle (SystemVerilog).
//
// Tools        : Verilator + cocotb; Yosys
//
// References   :
//   - AMBA AXI and ACE Protocol Specification (Arm IHI 0022), AXI4-Lite.
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

// axil_if.
//
// AXI4-Lite signal bundle: the aw/w/b/ar/r channel set, including
// awprot/arprot. ADDR_W/DATA_W are set where the interface is
// instantiated; wstrb is sized DATA_W/8 accordingly.
//
// Modports connect via .master (drives address/data/valid on the aw/w/ar
// channels, samples ready plus the b/r response channels) and .slave (the
// mirror image) -- interface ports must NOT be prefixed with input/output
// when declared on a module, direction comes from the modport alone
// (Yosys's read_verilog -sv rejects input/output on an interface-typed
// port).
//
// Channels and flow (each channel is an independent valid/ready handshake):
//   write: AW (address) and W (data) from the master, then B (response) back
//   read:  AR (address) from the master, then R (data + response) back
// bresp/rresp: 2'b00 = OKAY, 2'b10 = SLVERR, 2'b11 = DECERR.
//
// .. mermaid::
//    :caption: AXI4-Lite write and read transactions
//
//    sequenceDiagram
//      participant M as master (host)
//      participant S as slave (register file)
//      M->>S: AW (awaddr, awvalid) + W (wdata, wstrb, wvalid)
//      S-->>M: B (bresp, bvalid)
//      M->>S: AR (araddr, arvalid)
//      S-->>M: R (rdata, rresp, rvalid)
interface axil_if #(
  parameter int unsigned ADDR_W = 8,
  parameter int unsigned DATA_W = 32
);

  logic [ADDR_W-1:0]   awaddr;
  logic [2:0]          awprot;
  logic                awvalid;
  logic                awready;

  logic [DATA_W-1:0]   wdata;
  logic [DATA_W/8-1:0] wstrb;
  logic                wvalid;
  logic                wready;

  logic [1:0]          bresp;
  logic                bvalid;
  logic                bready;

  logic [ADDR_W-1:0]   araddr;
  logic [2:0]          arprot;
  logic                arvalid;
  logic                arready;

  logic [DATA_W-1:0]   rdata;
  logic [1:0]          rresp;
  logic                rvalid;
  logic                rready;

  modport master (
    output awaddr, awprot, awvalid, wdata, wstrb, wvalid, bready,
           araddr, arprot, arvalid, rready,
    input  awready, wready, bresp, bvalid, arready, rdata, rresp, rvalid
  );

  modport slave (
    input  awaddr, awprot, awvalid, wdata, wstrb, wvalid, bready,
           araddr, arprot, arvalid, rready,
    output awready, wready, bresp, bvalid, arready, rdata, rresp, rvalid
  );

// Yosys's read_verilog -sv rejects the optional end-label on `endinterface`
// (unlike `endmodule : name`, which it accepts) -- left unlabelled here.
endinterface
