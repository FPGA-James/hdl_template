// Hand-rolled AXI-Lite bus driver for native (framework-less) SystemVerilog
// testbenches. No off-the-shelf, non-UVM, Verilator-compatible SV AXI-Lite
// BFM was found (pulp-platform/axi's axi_test.sv was spiked directly and
// fails under Verilator on unused full-AXI classes) -- see
// docs/superpowers/specs/2026-08-21-testbenches-target-top-design.md.
// Single-beat only, no bursts, no backpressure injection: exactly what
// this project's test scenarios need, nothing more. A real BFM can
// replace this later without touching the testbench that calls it, as
// long as the axil_write/axil_read task signatures stay the same.
//
// Both tasks poll all of their channel's handshake signals in a single
// per-cycle loop rather than one dedicated wait per signal. A slave whose
// bvalid/rvalid is registered (asserted for exactly one cycle immediately
// after accepting aw+w or ar, decoupled from those request signals in the
// same timestep -- true of any synthesizable AXI-Lite slave, including
// this project's hdl_registers-generated register file) can pulse its
// response before a sequential "wait for awready, then wait for wready,
// then wait for bvalid" driver ever gets around to sampling it --
// verified empirically against a minimal always-ready AXI-Lite slave
// under Verilator, where the sequential form hung indefinitely.
// Assignments to the ref'd bus signals use blocking (=), not non-blocking
// (<=): Verilator does not propagate a non-blocking assignment made
// through a ref parameter to other processes observing the aliased net
// within the same timestep (confirmed by a monitor process reading a
// stale value the same cycle the task wrote it), so blocking assignment
// is required here for the write to be visible to the DUT on the correct
// edge.
//
// bready/rready are held one extra cycle past first observing bvalid/
// rvalid before being cleared, rather than cleared the same edge. This
// project's generated register file (PeakRDL-regblock) tracks response
// acceptance with a registered FIFO pointer that needs bvalid/bready (or
// rvalid/rready) to have been stable for a full clock cycle to correctly
// register an accept; clearing ready the same instant valid is first
// observed can leave that pointer permanently stuck (verified via direct
// hierarchical inspection of the generated file's response-FIFO state:
// the accept pointer never advanced, deadlocking every later transaction
// on that channel) -- this did not surface against the toy always-ready
// slave used above, which has no such backpressure-aware bookkeeping.
// For reads specifically, rdata must still be captured on the SAME cycle
// rvalid is first observed (rdata is only guaranteed valid while rvalid
// is asserted, and can go stale the instant rvalid drops once the FIFO
// pointer advances) -- only the rready clear is deferred, not the read.
package axi_lite_driver_pkg;

    task automatic axil_write(
        ref   logic        clk,
        ref   logic        awvalid, ref logic awready, ref logic [7:0]  awaddr,
        ref   logic        wvalid,  ref logic wready,  ref logic [31:0] wdata, ref logic [3:0] wstrb,
        ref   logic        bvalid,  ref logic bready,
        input logic [7:0]  addr,
        input logic [31:0] data
    );
        bit aw_done = 1'b0, w_done = 1'b0, resp_seen = 1'b0;
        awvalid = 1'b1; awaddr = addr;
        wvalid  = 1'b1; wdata  = data; wstrb = 4'b1111;
        bready  = 1'b1;
        forever begin
            @(posedge clk);
            if (!aw_done && awready) begin awvalid = 1'b0; aw_done = 1'b1; end
            if (!w_done && wready)   begin wvalid  = 1'b0; w_done  = 1'b1; end
            if (resp_seen) begin bready = 1'b0; break; end
            if (bvalid) resp_seen = 1'b1;
        end
    endtask

    task automatic axil_read(
        ref   logic        clk,
        ref   logic        arvalid, ref logic arready, ref logic [7:0]  araddr,
        ref   logic        rvalid,  ref logic rready,  ref logic [31:0] rdata,
        input logic [7:0]  addr,
        output logic [31:0] data
    );
        bit ar_done = 1'b0, resp_seen = 1'b0;
        arvalid = 1'b1; araddr = addr;
        rready  = 1'b1;
        forever begin
            @(posedge clk);
            if (!ar_done && arready) begin arvalid = 1'b0; ar_done = 1'b1; end
            if (resp_seen) begin rready = 1'b0; break; end
            if (rvalid) begin data = rdata; resp_seen = 1'b1; end
        end
    endtask

endpackage : axi_lite_driver_pkg
