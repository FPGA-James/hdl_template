library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

library work;
use work.<<NAME>>_pkg.all;

-- Native (framework-less) testbench for <<NAME>>_core, run directly with NVC
-- -- no VUnit/cocotb dependency. Self-checking via assert/report; exits
-- non-zero on any unhandled failure.
--
--   make sim-native TOPLEVEL_HDL=vhdl
--
-- Or directly:
--   nvc --std=2008 -a src/vhdl/<<NAME>>_pkg.vhd src/vhdl/<<NAME>>_core.vhd \
--     tb/native/vhdl/<<NAME>>_tb.vhd
--   nvc -e <<NAME>>_tb
--   nvc -r <<NAME>>_tb
--
-- Test cases:
--   count_up    -- count increments on each pulse when enabled
--   saturation  -- counter saturates at (2**C_COUNT_W)-1
--   reset_count -- reset_count_i clears count in one cycle
--   disable     -- count holds when enable_i is deasserted
entity <<NAME>>_tb is
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
    -- the caller reads them.
    procedure clk_edge is
    begin
        wait until rising_edge(clk);
        wait for 1 ps;
    end procedure;

    procedure check_equal(actual, expected : unsigned; msg : string) is
    begin
        assert actual = expected
            report "FAIL: " & msg & " -- expected " & integer'image(to_integer(expected)) &
                   " got " & integer'image(to_integer(actual))
            severity failure;
    end procedure;

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
        -- Release reset
        clk_edge;
        rst_n <= '1';
        clk_edge;

        -- ── count_up ──────────────────────────────────────────────────────
        enable_i    <= '1';
        increment_i <= 1;
        for i in 1 to 8 loop
            clk_edge;
            check_equal(unsigned(pulse_count_o), to_unsigned(i, C_COUNT_W), "count_up");
        end loop;
        assert enabled_o = '1' report "FAIL: enabled_o should be high when counting" severity failure;

        -- ── saturation ────────────────────────────────────────────────────
        increment_i <= 255;
        -- Wind the counter close to saturation
        for i in 1 to (2**C_COUNT_W - 1) / 255 + 2 loop
            clk_edge;
        end loop;
        check_equal(unsigned(pulse_count_o), to_unsigned(2**C_COUNT_W - 1, C_COUNT_W),
            "saturation");

        -- ── reset_count ───────────────────────────────────────────────────
        -- One-cycle pulse: check the count immediately after the edge it
        -- was sampled on, before any further counting can occur.
        reset_count_i <= '1';
        clk_edge;
        check_equal(unsigned(pulse_count_o), to_unsigned(0, C_COUNT_W), "reset_count");
        reset_count_i <= '0';

        -- ── disable ───────────────────────────────────────────────────────
        increment_i <= 1;
        enable_i    <= '1';
        for i in 1 to 4 loop
            clk_edge;
        end loop;
        check_equal(unsigned(pulse_count_o), to_unsigned(4, C_COUNT_W), "disable: count before disable");

        enable_i <= '0';
        for i in 1 to 4 loop
            clk_edge;
        end loop;
        check_equal(unsigned(pulse_count_o), to_unsigned(4, C_COUNT_W),
            "disable: count should hold");
        assert enabled_o = '0' report "FAIL: enabled_o should be low when disabled" severity failure;

        report "PASS: all native VHDL tests completed" severity note;
        std.env.finish;
        wait;
    end process main;

    -- Watchdog: fail the test if it runs for more than 1 ms.
    watchdog : process is
    begin
        wait for 1 ms;
        assert false report "FAIL: watchdog timeout" severity failure;
        std.env.finish;
    end process watchdog;

end architecture bench;
