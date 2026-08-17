library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library vunit_lib;
context vunit_lib.vunit_context;

library rtl_lib;
use rtl_lib.<<NAME>>_pkg.all;

-- VUnit testbench for <<NAME>>_core.
--
-- Exercises the pulse counter logic directly without the AXI-Lite register
-- block. Register integration is tested separately via cocotb + the top-level.
--
-- Test cases:
--   test_count_up    — count increments on each pulse when enabled
--   test_saturation  — counter saturates at (2**C_COUNT_W)-1
--   test_reset_count — reset_count_i clears count in one cycle
--   test_disable     — count holds when enable_i is deasserted
entity <<NAME>>_tb is
    generic (runner_cfg : string);
end entity <<NAME>>_tb;

architecture bench of <<NAME>>_tb is

    -- DUT stimulus
    signal clk           : std_logic := '0';
    signal rst_n         : std_logic := '0';
    signal enable_i      : std_logic := '0';
    signal increment_i   : integer range 1 to 255 := 1;
    signal reset_count_i : std_logic := '0';

    -- DUT response
    signal enabled_o     : std_logic;
    signal pulse_count_o : std_logic_vector(C_COUNT_W-1 downto 0);

    -- 10 ns clock (100 MHz)
    constant C_CLK_PERIOD : time := 10 ns;

    -- Wait for the next rising edge, then a further delta past it so that
    -- clocked outputs (registered on this same edge) have settled before
    -- the caller reads them. Without this, a check placed immediately after
    -- `wait until rising_edge(clk)` reads the pre-edge value, since a signal
    -- assignment is never visible until the delta cycle after it is scheduled.
    procedure clk_edge is
    begin
        wait until rising_edge(clk);
        wait for 1 ps;
    end procedure;

begin

    clk <= not clk after C_CLK_PERIOD / 2;

    -- DUT instantiation
    u_dut : entity rtl_lib.<<NAME>>_core
        port map (
            clk           => clk,
            rst_n         => rst_n,
            enable_i      => enable_i,
            increment_i   => increment_i,
            reset_count_i => reset_count_i,
            enabled_o     => enabled_o,
            pulse_count_o => pulse_count_o
        );

    main : process is
    begin
        test_runner_setup(runner, runner_cfg);

        -- Release reset
        clk_edge;
        rst_n <= '1';
        clk_edge;

        -- ── test_count_up ─────────────────────────────────────────────────
        if run("test_count_up") then
            enable_i    <= '1';
            increment_i <= 1;
            for i in 1 to 8 loop
                clk_edge;
                check_equal(unsigned(pulse_count_o), to_unsigned(i, C_COUNT_W),
                    "count_up: expected " & integer'image(i));
            end loop;
            check_equal(enabled_o, '1', "enabled_o should be high when counting");
        end if;

        -- ── test_saturation ───────────────────────────────────────────────
        if run("test_saturation") then
            enable_i    <= '1';
            increment_i <= 255;
            -- Wind the counter close to saturation
            for i in 1 to (2**C_COUNT_W - 1) / 255 + 2 loop
                clk_edge;
            end loop;
            check_equal(unsigned(pulse_count_o), to_unsigned(2**C_COUNT_W - 1, C_COUNT_W),
                "counter should saturate at max value");
        end if;

        -- ── test_reset_count ──────────────────────────────────────────────
        -- One-cycle pulse: check the count immediately after the edge it
        -- was sampled on, before any further counting can occur.
        if run("test_reset_count") then
            enable_i    <= '1';
            increment_i <= 1;
            for i in 1 to 5 loop
                clk_edge;
            end loop;
            check_equal(unsigned(pulse_count_o), to_unsigned(5, C_COUNT_W), "count before reset");

            reset_count_i <= '1';
            clk_edge;
            check_equal(unsigned(pulse_count_o), to_unsigned(0, C_COUNT_W), "count after reset");
            reset_count_i <= '0';
        end if;

        -- ── test_disable ──────────────────────────────────────────────────
        if run("test_disable") then
            enable_i    <= '1';
            increment_i <= 1;
            for i in 1 to 4 loop
                clk_edge;
            end loop;
            check_equal(unsigned(pulse_count_o), to_unsigned(4, C_COUNT_W), "count before disable");

            enable_i <= '0';
            for i in 1 to 4 loop
                clk_edge;
            end loop;
            check_equal(unsigned(pulse_count_o), to_unsigned(4, C_COUNT_W),
                "count should hold when disabled");
            check_equal(enabled_o, '0', "enabled_o should be low when disabled");
        end if;

        test_runner_cleanup(runner);
    end process main;

    -- Watchdog: fail the test if it runs for more than 1 ms.
    test_runner_watchdog(runner, 1 ms);

end architecture bench;
