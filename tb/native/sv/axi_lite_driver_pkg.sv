// Hand-rolled AXI-Lite bus driver for native (framework-less) SystemVerilog
// testbenches. No off-the-shelf, non-UVM, Verilator-compatible SV AXI-Lite
// BFM was found (pulp-platform/axi's axi_test.sv was spiked directly and
// fails under Verilator on unused full-AXI classes) -- see
// docs/superpowers/specs/2026-08-21-testbenches-target-top-design.md.
// Single-beat only, no bursts, no backpressure injection: exactly what
// this project's test scenarios need, nothing more. A real BFM can
// replace this later without touching the testbench that calls it, as
// long as the axil_write/axil_read task signatures stay the same.
package axi_lite_driver_pkg;

    task automatic axil_write(
        ref   logic        clk,
        ref   logic        awvalid, ref logic awready, ref logic [7:0]  awaddr,
        ref   logic        wvalid,  ref logic wready,  ref logic [31:0] wdata, ref logic [3:0] wstrb,
        ref   logic        bvalid,  ref logic bready,
        input logic [7:0]  addr,
        input logic [31:0] data
    );
        awvalid = 1'b1; awaddr = addr;
        wvalid  = 1'b1; wdata  = data; wstrb = 4'b1111;
        bready  = 1'b1;
        do @(posedge clk); while (!awready);
        awvalid = 1'b0;
        do @(posedge clk); while (!wready);
        wvalid = 1'b0;
        do @(posedge clk); while (!bvalid);
        bready = 1'b0;
    endtask

    task automatic axil_read(
        ref   logic        clk,
        ref   logic        arvalid, ref logic arready, ref logic [7:0]  araddr,
        ref   logic        rvalid,  ref logic rready,  ref logic [31:0] rdata,
        input logic [7:0]  addr,
        output logic [31:0] data
    );
        arvalid = 1'b1; araddr = addr;
        rready  = 1'b1;
        do @(posedge clk); while (!arready);
        arvalid = 1'b0;
        do @(posedge clk); while (!rvalid);
        data = rdata;
        rready = 1'b0;
    endtask

endpackage : axi_lite_driver_pkg
