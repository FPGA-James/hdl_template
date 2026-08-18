// <<NAME>> core (SystemVerilog).
//
// Parameterisable pulse counter. Port interface is identical to the VHDL
// <<NAME>>_core entity so that the same cocotb test suite covers both.
//
// Register interface:
//   enable_i      -- enables counting
//   increment_i   -- step size per pulse (1..255)
//   reset_count_i -- one-cycle pulse clears the count
//   enabled_o     -- high when counter is active
//   pulse_count_o -- current count value
//
// Instantiated by: <<NAME>>_top (sv variant)
module <<NAME>>_core
#(
    // Override the package default if needed.
    parameter int unsigned COUNT_W = <<NAME>>_pkg::C_COUNT_W
) (
    // System clock, rising-edge triggered.
    input  logic              clk,
    // Synchronous active-low reset.
    input  logic              rst_n,

    // ── From register block ─────────────────────────────────────────────────
    // Enable counting when asserted.
    input  logic              enable_i,
    // Step size added to count on each qualifying pulse.
    input  int unsigned       increment_i,
    // Held-level reset request. Core detects the rising edge internally and
    // clears the count for exactly one cycle.
    input  logic              reset_count_i,

    // ── To register block ───────────────────────────────────────────────────
    // Asserted whenever enable_i is high and counting is not in reset.
    output logic              enabled_o,
    // Running pulse count, saturates at (2**COUNT_W)-1.
    output logic [COUNT_W-1:0] pulse_count_o
);

    logic [COUNT_W:0] count_ext;  // one extra bit for saturation detection
    logic [COUNT_W-1:0] count_r;

    // Registered previous value of reset_count_i, used to derive a
    // one-cycle internal pulse from what is now a held-level input (the
    // register file no longer auto-clears it after one cycle).
    logic reset_count_prev;
    logic reset_count_pulse;

    assign reset_count_pulse = reset_count_i & ~reset_count_prev;

    // p_count: Clocked pulse counter with saturating addition.
    //
    // Priority: reset > reset_count pulse > counting
    always_ff @(posedge clk) begin
        reset_count_prev <= reset_count_i;

        if (!rst_n) begin
            count_r   <= '0;
            enabled_o <= 1'b0;
        end else if (reset_count_pulse) begin
            count_r   <= '0;
            enabled_o <= enable_i;
        end else if (enable_i) begin
            // Promote to COUNT_W+1 bits for saturation check.
            count_ext = {1'b0, count_r} + COUNT_W'(increment_i);
            count_r   <= count_ext[COUNT_W] ? '1 : count_ext[COUNT_W-1:0];
            enabled_o <= 1'b1;
        end else begin
            enabled_o <= 1'b0;
        end
    end

    assign pulse_count_o = count_r;

endmodule : <<NAME>>_core
