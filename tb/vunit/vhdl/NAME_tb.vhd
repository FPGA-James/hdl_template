library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library vunit_lib;
context vunit_lib.vunit_context;

library work;
use work.<<NAME>>_pkg.all;

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

begin

    clk <= not clk after C_CLK_PERIOD / 2;

    -- DUT instantiation
    u_dut : entity work.<<NAME>>_core
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
        wait until rising_edge(clk);
        rst_n <= '1';
        wait until rising_edge(clk);

        -- ── test_count_up ─────────────────────────────────────────────────
        if run("test_count_up") then
            enable_i    <= '1';
            increment_i <= 1;
            for i in 1 to 8 loop
                wait until rising_edge(clk);
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
                wait until rising_edge(clk);
            end loop;
            check_equal(unsigned(pulse_count_o), to_unsigned(2**C_COUNT_W - 1, C_COUNT_W),
                "counter should saturate at max value");
        end if;

        -- ── test_reset_count ──────────────────────────────────────────────
        if run("test_reset_count") then
            enable_i    <= '1';
            increment_i <= 1;
            for i in 1 to 5 loop
                wait until rising_edge(clk);
            end loop;
            check_equal(unsigned(pulse_count_o), to_unsigned(5, C_COUNT_W), "count before reset");

            reset_count_i <= '1';
            wait until rising_edge(clk);
            reset_count_i <= '0';
            wait until rising_edge(clk);
            check_equal(unsigned(pulse_count_o), to_unsigned(0, C_COUNT_W), "count after reset");
        end if;

        -- ── test_disable ──────────────────────────────────────────────────
        if run("test_disable") then
            enable_i    <= '1';
            increment_i <= 1;
            for i in 1 to 4 loop
                wait until rising_edge(clk);
            end loop;
            check_equal(unsigned(pulse_count_o), to_unsigned(4, C_COUNT_W), "count before disable");

            enable_i <= '0';
            for i in 1 to 4 loop
                wait until rising_edge(clk);
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
