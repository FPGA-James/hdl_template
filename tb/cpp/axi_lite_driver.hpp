// Hand-rolled AXI-Lite bus driver for Verilator C++ testbenches. No
// off-the-shelf AXI-Lite C++ VIP was targeted for this project -- a small
// hand-rolled driver operating directly on the Verilated model's port
// members is the conventional, idiomatic way to write a Verilator C++
// harness for a simple bus like this. Single-beat only, no bursts.
//
// This is the third hand-rolled AXI-Lite driver in this project (after the
// native SystemVerilog driver in tb/native/sv/axi_lite_driver_pkg.sv and
// the OSVVM-based VHDL driver used by the VUnit path). Both of those went
// through the same two empirically-discovered fixes over a naive
// sequential-poll driver, and this driver's write()/read() are written in
// the same shape from the start rather than re-discovering them:
//
// 1. Polling each channel's handshake signals in one unified per-cycle
//    loop, not a separate dedicated wait per signal. A slave whose
//    bvalid/rvalid is registered (asserted for exactly one cycle
//    immediately after accepting aw+w or ar, decoupled from those request
//    signals) -- true of any synthesizable AXI-Lite slave, including this
//    project's hdl_registers-generated register file -- can pulse its
//    response before a sequential "wait for awready, then wait for
//    wready, then wait for bvalid" driver ever gets around to sampling
//    it, hanging forever. Polling all of a channel's conditions together
//    every cycle avoids this regardless of simulation model, since it is
//    a property of the DUT's handshake timing, not of how the simulator
//    schedules processes.
//
// 2. bready/rready are held one extra tick() past first observing
//    bvalid/rvalid before being cleared, rather than cleared the same
//    tick(). This project's generated register file (PeakRDL-regblock)
//    tracks response acceptance with a registered FIFO pointer that needs
//    bvalid/bready (or rvalid/rready) to have been stable for a full
//    clock cycle to correctly register an accept; clearing ready the same
//    instant valid is first observed can leave that pointer permanently
//    stuck -- the same root cause the SV driver
//    (tb/native/sv/axi_lite_driver_pkg.sv) hit under Verilator
//    --binary --timing (see Task 8's report).
//
//    This was NOT assumed to carry over here: Verilator's --cc --exe
//    --build model is meaningfully different (an explicit,
//    single-threaded tick() that calls eval() to fully settle the DUT
//    before this driver code decides what to change next, vs. genuine
//    concurrent-process/NBA scheduling under --binary --timing), so it
//    was plausible this driver's same-edge accept-then-clear wouldn't hit
//    the same race. It was tested directly: a same-tick()-clear version
//    of write()/read() (clearing bready/rready in the same branch that
//    first observes bvalid/rvalid, no resp_seen deferral) was built and
//    run against the real generated register file and hung indefinitely
//    every time (confirmed via `ps` showing the compiled testbench
//    pegged at 100% CPU with zero progress, not a slow pass). So the
//    DUT-side registered FIFO-pointer requirement applies regardless of
//    simulator scheduling model, as expected for a synchronous-design
//    property, and the one-cycle hold below is required, not just
//    precautionary.
//    Read data is still captured in the same branch that observes
//    rvalid, not deferred: rdata is only guaranteed valid while rvalid is
//    asserted and can go stale once the accept pointer advances, so only
//    the ready-clear is deferred, never the data capture.
#pragma once

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <functional>

// Template on the Verilated top-level type so this driver has zero
// dependency on any specific project's generated class name.
template <typename Top>
class AxiLiteDriver {
public:
    // A stuck handshake (a real regression, not expected in normal use)
    // would otherwise spin write()/read()'s polling loop forever with no
    // output, unlike the SV/VHDL native testbenches' explicit watchdog
    // processes -- this cap makes that failure mode exit with a clear
    // message instead of hanging the calling `make sim-cpp` indefinitely.
    static constexpr int kMaxWaitCycles = 1000;

    explicit AxiLiteDriver(Top* top) : top_(top) {}

    void write(uint8_t addr, uint32_t data) {
        bool aw_done = false, w_done = false, resp_seen = false;
        top_->s_axi_awvalid = 1; top_->s_axi_awaddr = addr;
        top_->s_axi_wvalid  = 1; top_->s_axi_wdata  = data; top_->s_axi_wstrb = 0xF;
        top_->s_axi_bready  = 1;
        for (int cycles = 0; ; cycles++) {
            if (cycles >= kMaxWaitCycles) {
                fprintf(stderr, "FAIL: axil_write watchdog -- no response after %d cycles\n", kMaxWaitCycles);
                exit(1);
            }
            tick();
            if (!aw_done && top_->s_axi_awready) { top_->s_axi_awvalid = 0; aw_done = true; }
            if (!w_done && top_->s_axi_wready)   { top_->s_axi_wvalid  = 0; w_done  = true; }
            if (resp_seen) { top_->s_axi_bready = 0; break; }
            if (top_->s_axi_bvalid) resp_seen = true;
        }
    }

    uint32_t read(uint8_t addr) {
        bool ar_done = false, resp_seen = false;
        uint32_t data = 0;
        top_->s_axi_arvalid = 1; top_->s_axi_araddr = addr;
        top_->s_axi_rready  = 1;
        for (int cycles = 0; ; cycles++) {
            if (cycles >= kMaxWaitCycles) {
                fprintf(stderr, "FAIL: axil_read watchdog -- no response after %d cycles\n", kMaxWaitCycles);
                exit(1);
            }
            tick();
            if (!ar_done && top_->s_axi_arready) { top_->s_axi_arvalid = 0; ar_done = true; }
            if (resp_seen) { top_->s_axi_rready = 0; break; }
            if (top_->s_axi_rvalid) { data = top_->s_axi_rdata; resp_seen = true; }
        }
        return data;
    }

    // Advance one clock cycle: caller supplies how, since the exact
    // eval()/time-advance sequence is test-harness-specific.
    std::function<void()> tick;

private:
    Top* top_;
};
