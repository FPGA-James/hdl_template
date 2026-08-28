library ieee;
use ieee.std_logic_1164.all;

library vunit_lib;
context vunit_lib.vunit_context;
-- VUnit 5's vunit_context no longer pulls in com_context (unlike VUnit 4.x),
-- so the shared message-passing "net" signal needs an explicit import here
-- -- matches the pattern used by hdl-modules' own testbenches (e.g.
-- tb_axi_lite_register_file.vhd) that drive a BFM via generated/handwritten
-- read/write procedures.
use vunit_lib.com_pkg.net;
use vunit_lib.com_types_pkg.network_t;

library axi_lite;
use axi_lite.axi_lite_pkg.all;

-- BFM library (hdl-modules) -- referenced by name below (bfm.axi_lite_master),
-- so it needs an explicit library clause even though there's no top-level
-- "use" from it.
library bfm;

library rtl_lib;
use rtl_lib.<<NAME>>_pkg.all;
use rtl_lib.<<NAME>>_regs_pkg.all;
use rtl_lib.<<NAME>>_register_read_write_pkg.all;

-- VUnit testbench for <<NAME>>_top.
--
-- Drives the design through its real AXI-Lite register interface (via
-- hdl-modules' axi_lite_master BFM) rather than <<NAME>>_core's plain ports
-- directly -- this exercises the auto-wired register integration, not just
-- the core counter logic.
--
-- Test cases:
--   test_count_up    — count increments on each pulse when enabled
--   test_saturation  — counter saturates at (2**C_COUNT_W)-1
--   test_reset_count — reset_count clears count in one cycle
--   test_disable     — count holds when enable is deasserted
entity <<NAME>>_tb is
    generic (runner_cfg : string);
end entity <<NAME>>_tb;

architecture bench of <<NAME>>_tb is

    signal clk       : std_logic := '0';
    signal rst_n     : std_logic := '0';
    signal pulse_i   : std_logic := '0';

    signal s_axi_m2s : axi_lite_m2s_t;
    signal s_axi_s2m : axi_lite_s2m_t;

    -- 10 ns clock (100 MHz)
    constant C_CLK_PERIOD : time := 10 ns;

    procedure clk_edge is
    begin
        wait until rising_edge(clk);
        wait for 1 ps;
    end procedure;

    -- Small read helpers to keep the test body readable.
    --
    -- These must be plain procedures, not (impure) functions: the generated
    -- read_<<NAME>>_status_* procedures take "signal net : inout network_t",
    -- and VHDL forbids a function from calling a procedure with an out/inout
    -- signal parameter (a function may not create signal drivers, directly
    -- or transitively -- GHDL rejects it with "signal net is not a formal
    -- parameter" if attempted as a function).
    --
    -- A procedure alone isn't enough either: an architecture-level procedure
    -- (declared outside any process, as these are) can't forward an
    -- externally-visible signal like "net" into another subprogram's
    -- out/inout signal formal unless it declares that same signal as one of
    -- its own formal parameters too -- otherwise GHDL rejects it with the
    -- same "signal net is not a formal parameter" error, since the compiler
    -- can't statically bind the resulting driver to a single process.
    -- Declaring "signal net : inout network_t" here and passing the caller's
    -- "net" explicitly at each call site (see the main process below) is the
    -- standard VUnit idiom for this.
    procedure read_pulse_count(signal net : inout network_t; value : out integer) is
    begin
        read_<<NAME>>_status_pulse_count(net, value);
    end procedure;

    procedure read_enabled(signal net : inout network_t; value : out std_ulogic) is
    begin
        read_<<NAME>>_status_enabled(net, value);
    end procedure;

begin

    clk <= not clk after C_CLK_PERIOD / 2;

    -- DUT instantiation: <<NAME>>_top, not <<NAME>>_core.
    u_dut : entity rtl_lib.<<NAME>>_top
        port map (
            clk       => clk,
            rst_n     => rst_n,
            pulse_i   => pulse_i,
            s_axi_m2s => s_axi_m2s,
            s_axi_s2m => s_axi_s2m
        );

    -- AXI-Lite bus master BFM, driven by the generated read/write
    -- procedures below via VUnit's message-passing bus_handle.
    u_axi_lite_master : entity bfm.axi_lite_master
        port map (
            clk          => clk,
            axi_lite_m2s => s_axi_m2s,
            axi_lite_s2m => s_axi_s2m
        );

    main : process is
        variable pulse_count : integer;
        variable enabled     : std_ulogic;
        -- Baseline/reference snapshots -- see note below on why the test
        -- bodies compare deltas against these rather than assuming a known
        -- absolute count right after a register write.
        variable baseline    : integer;
    begin
        test_runner_setup(runner, runner_cfg);

        -- Release reset
        clk_edge;
        rst_n <= '1';
        clk_edge;

        -- Each register write below is a real AXI-Lite bus transaction (and
        -- write_..._conf_* is a read-modify-write: two transactions), taking
        -- several clock cycles to complete via the axi_lite_master BFM --
        -- unlike a direct port assignment, it does not take effect on the
        -- next clk_edge. The counter keeps counting every cycle once
        -- enabled, including during those in-flight transactions (and
        -- during the read_pulse_count call used to observe it, which is
        -- itself a bus transaction), so an absolute "count == N" check
        -- against a live, still-counting register cannot be exact -- the
        -- read that captures the "final" value is itself preceded by a few
        -- more live cycles of counting than the plain clk_edge waits alone
        -- account for. Each test below takes an explicit baseline reading,
        -- then asserts the delta over a fixed number of plain clk_edge
        -- waits is *at least* the expected count (proving real counting
        -- happened; it can only ever be undercounted if counting were
        -- broken, never overcounted below the true elapsed-cycle minimum).
        -- Checks against a register that is known to be stable (counting
        -- disabled) use exact equality instead, since nothing can perturb
        -- those between reads.

        -- ── test_count_up ─────────────────────────────────────────────────
        if run("test_count_up") then
            write_<<NAME>>_conf_increment(net, 1);
            write_<<NAME>>_conf_enable(net, '1');
            read_pulse_count(net, baseline);
            for i in 1 to 8 loop
                clk_edge;
            end loop;
            read_pulse_count(net, pulse_count);
            check(pulse_count - baseline >= 8,
                "count_up: expected at least 8 more counts after 8 cycles, got "
                & integer'image(pulse_count - baseline));
            read_enabled(net, enabled);
            check_equal(enabled, '1', "enabled should be high when counting");
        end if;

        -- ── test_saturation ───────────────────────────────────────────────
        if run("test_saturation") then
            write_<<NAME>>_conf_increment(net, 255);
            write_<<NAME>>_conf_enable(net, '1');
            for i in 1 to (2**C_COUNT_W - 1) / 255 + 2 loop
                clk_edge;
            end loop;
            read_pulse_count(net, pulse_count);
            check_equal(pulse_count, 2**C_COUNT_W - 1, "counter should saturate at max value");
        end if;

        -- ── test_reset_count ──────────────────────────────────────────────
        if run("test_reset_count") then
            write_<<NAME>>_conf_increment(net, 1);
            write_<<NAME>>_conf_enable(net, '1');
            read_pulse_count(net, baseline);
            for i in 1 to 5 loop
                clk_edge;
            end loop;
            read_pulse_count(net, pulse_count);
            check(pulse_count - baseline >= 5,
                "count before reset: expected at least 5 more counts, got "
                & integer'image(pulse_count - baseline));

            -- Disable counting first so the "count after reset" check below
            -- is deterministic: reset_count derives a one-cycle internal
            -- pulse from the write below, but the counter (if still
            -- enabled) would otherwise resume counting again on the very
            -- next cycle -- including during the second (write-0) bus
            -- transaction and the read that follows it -- before this
            -- process ever observes the momentarily-zero value.
            write_<<NAME>>_conf_enable(net, '0');
            write_<<NAME>>_command_reset_count(net, '1');
            clk_edge;
            write_<<NAME>>_command_reset_count(net, '0');
            read_pulse_count(net, pulse_count);
            check_equal(pulse_count, 0, "count after reset");
        end if;

        -- ── test_disable ──────────────────────────────────────────────────
        if run("test_disable") then
            write_<<NAME>>_conf_increment(net, 1);
            write_<<NAME>>_conf_enable(net, '1');
            read_pulse_count(net, baseline);
            for i in 1 to 4 loop
                clk_edge;
            end loop;
            write_<<NAME>>_conf_enable(net, '0');
            read_pulse_count(net, pulse_count);
            check(pulse_count - baseline >= 4,
                "count before disable: expected at least 4 more counts, got "
                & integer'image(pulse_count - baseline));
            baseline := pulse_count;

            for i in 1 to 4 loop
                clk_edge;
            end loop;
            read_pulse_count(net, pulse_count);
            check_equal(pulse_count, baseline, "count should hold when disabled");
            read_enabled(net, enabled);
            check_equal(enabled, '0', "enabled should be low when disabled");
        end if;

        test_runner_cleanup(runner);
    end process main;

    test_runner_watchdog(runner, 1 ms);

end architecture bench;
