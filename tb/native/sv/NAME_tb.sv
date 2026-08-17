// Native (framework-less) testbench for <<NAME>>_core, run directly via the
// simulator's --binary mode -- no cocotb dependency, no DPI/C++ wrapper.
// Self-checking via $fatal; exits non-zero on any unhandled failure.
//
//   make sim-native TOPLEVEL_HDL=sv
//
// Or directly:
//   $ verilator --binary --timing --top-module <<NAME>>_tb \
//       src/sv/<<NAME>>_pkg.sv src/sv/<<NAME>>_core.sv tb/native/sv/<<NAME>>_tb.sv
//   $ ./obj_dir/V<<NAME>>_tb
//
// Test cases:
//   count_up    -- count increments on each pulse when enabled
//   saturation  -- counter saturates at (2**C_COUNT_W)-1
//   reset_count -- reset_count_i clears count in one cycle
//   disable     -- count holds when enable_i is deasserted
module <<NAME>>_tb;
    import <<NAME>>_pkg::*;

    // DUT stimulus
    logic               clk = 1'b0;
    logic               rst_n = 1'b0;
    logic               enable_i = 1'b0;
    int unsigned        increment_i = 1;
    logic               reset_count_i = 1'b0;

    // DUT response
    logic                  enabled_o;
    logic [C_COUNT_W-1:0]  pulse_count_o;

    // 10 ns clock (100 MHz)
    localparam time C_CLK_PERIOD = 10ns;

    always #(C_CLK_PERIOD / 2) clk = ~clk;

    // DUT instantiation
    <<NAME>>_core u_dut (
        .clk           (clk),
        .rst_n         (rst_n),
        .enable_i      (enable_i),
        .increment_i   (increment_i),
        .reset_count_i (reset_count_i),
        .enabled_o     (enabled_o),
        .pulse_count_o (pulse_count_o)
    );

    // Wait for the next rising edge, then a further delta past it so that
    // clocked outputs (registered on this same edge) have settled before
    // the caller reads them.
    task automatic clk_edge;
        @(posedge clk);
        #1;
    endtask

    task automatic check_equal(int unsigned actual, int unsigned expected, string msg);
        if (actual !== expected) begin
            $error("FAIL: %s -- expected %0d got %0d", msg, expected, actual);
            $fatal(1);
        end
    endtask

    initial begin
        // Release reset
        clk_edge();
        rst_n = 1'b1;
        clk_edge();

        // ── count_up ─────────────────────────────────────────────────────
        enable_i    = 1'b1;
        increment_i = 1;
        for (int i = 1; i <= 8; i++) begin
            clk_edge();
            check_equal(pulse_count_o, i, "count_up");
        end
        if (enabled_o !== 1'b1) begin
            $error("FAIL: enabled_o should be high when counting");
            $fatal(1);
        end

        // ── saturation ───────────────────────────────────────────────────
        increment_i = 255;
        // Wind the counter close to saturation
        for (int i = 1; i <= (2 ** C_COUNT_W - 1) / 255 + 2; i++) begin
            clk_edge();
        end
        check_equal(pulse_count_o, (2 ** C_COUNT_W) - 1, "saturation");

        // ── reset_count ──────────────────────────────────────────────────
        // One-cycle pulse: check the count immediately after the edge it
        // was sampled on, before any further counting can occur.
        reset_count_i = 1'b1;
        clk_edge();
        check_equal(pulse_count_o, 0, "reset_count");
        reset_count_i = 1'b0;

        // ── disable ──────────────────────────────────────────────────────
        increment_i = 1;
        enable_i    = 1'b1;
        for (int i = 1; i <= 4; i++) begin
            clk_edge();
        end
        check_equal(pulse_count_o, 4, "disable: count before disable");

        enable_i = 1'b0;
        for (int i = 1; i <= 4; i++) begin
            clk_edge();
        end
        check_equal(pulse_count_o, 4, "disable: count should hold");
        if (enabled_o !== 1'b0) begin
            $error("FAIL: enabled_o should be low when disabled");
            $fatal(1);
        end

        $display("PASS: all native SystemVerilog tests completed");
        $finish;
    end

    // Watchdog: fail the test if it runs for more than 1 ms.
    initial begin
        #1ms;
        $error("FAIL: watchdog timeout");
        $fatal(1);
    end

endmodule : <<NAME>>_tb
