-- uart_tb.vhd
--
-- VUnit testbench for uart_core.
--
-- Exercises the UART TX and RX paths directly without the AXI4-Lite register
-- block.  A small baud divisor (C_BAUD_DIV = 32) is used to keep simulation
-- fast.  The loopback test uses the internal loopback path so both TX and RX
-- are exercised together.
--
-- Test cases:
--   test_tx_loopback     — send a byte via AXI-Stream TX, receive via AXI-Stream RX
--                          using the internal loopback path
--   test_rx_byte         — drive uart_rx_i manually, verify AXI-Stream RX output
--   test_tx_busy         — tx_busy_o is asserted during transmission, deasserts after
--   test_rx_frame_error  — bad stop bit triggers rx_frame_err_o

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library vunit_lib;
context vunit_lib.vunit_context;

library work;
use work.uart_pkg.all;

entity uart_tb is
    generic (runner_cfg : string);
end entity uart_tb;

architecture bench of uart_tb is

    -- Small baud divisor for fast simulation (100 MHz / 32 ≈ 3.125 Mbaud)
    constant C_BAUD_DIV   : integer := 32;
    constant C_CLK_PERIOD : time    := 10 ns;

    -- DUT stimulus
    signal clk            : std_logic := '0';
    signal rst_n          : std_logic := '0';
    signal tx_enable_i    : std_logic := '0';
    signal rx_enable_i    : std_logic := '0';
    signal loopback_i     : std_logic := '0';
    signal baud_div_i     : integer range 2 to 65535 := C_BAUD_DIV;
    signal s_axis_tdata   : std_logic_vector(C_DATA_W-1 downto 0) := (others => '0');
    signal s_axis_tvalid  : std_logic := '0';
    signal s_axis_tlast   : std_logic := '1';   -- always last for UART (one byte = one packet)
    signal uart_rx_i      : std_logic := '1';   -- idle high
    signal m_axis_tready  : std_logic := '0';

    -- DUT response
    signal tx_busy_o      : std_logic;
    signal rx_frame_err_o : std_logic;
    signal rx_overflow_o  : std_logic;
    signal s_axis_tready  : std_logic;
    signal m_axis_tdata   : std_logic_vector(C_DATA_W-1 downto 0);
    signal m_axis_tvalid  : std_logic;
    signal m_axis_tlast   : std_logic;
    signal uart_tx_o      : std_logic;

    -- Helper: wait N rising clock edges
    procedure wait_clk(n : in positive) is
    begin
        for i in 1 to n loop
            wait until rising_edge(clk);
        end loop;
    end procedure;

begin

    clk <= not clk after C_CLK_PERIOD / 2;

    u_dut : entity work.uart_core
        port map (
            clk            => clk,
            rst_n          => rst_n,
            tx_enable_i    => tx_enable_i,
            rx_enable_i    => rx_enable_i,
            loopback_i     => loopback_i,
            baud_div_i     => baud_div_i,
            tx_busy_o      => tx_busy_o,
            rx_frame_err_o => rx_frame_err_o,
            rx_overflow_o  => rx_overflow_o,
            s_axis_tdata   => s_axis_tdata,
            s_axis_tvalid  => s_axis_tvalid,
            s_axis_tready  => s_axis_tready,
            s_axis_tlast   => s_axis_tlast,
            m_axis_tdata   => m_axis_tdata,
            m_axis_tvalid  => m_axis_tvalid,
            m_axis_tready  => m_axis_tready,
            m_axis_tlast   => m_axis_tlast,
            uart_tx_o      => uart_tx_o,
            uart_rx_i      => uart_rx_i
        );

    main : process is

        -- Drive uart_rx_i with one 8N1 UART frame (LSB first).
        -- Each bit is held for C_BAUD_DIV clock cycles.
        procedure uart_rx_send(byte : in std_logic_vector(C_DATA_W-1 downto 0)) is
        begin
            uart_rx_i <= '0';               -- start bit
            wait_clk(C_BAUD_DIV);
            for b in 0 to C_DATA_W-1 loop
                uart_rx_i <= byte(b);
                wait_clk(C_BAUD_DIV);
            end loop;
            uart_rx_i <= '1';               -- stop bit
            wait_clk(C_BAUD_DIV);
        end procedure;

    begin
        test_runner_setup(runner, runner_cfg);

        -- Release reset after one clock
        wait until rising_edge(clk);
        rst_n <= '1';
        wait_clk(2);

        -- ── test_tx_loopback ─────────────────────────────────────────────────
        -- Enable TX + RX with loopback, send 0xA5, expect to receive 0xA5.
        if run("test_tx_loopback") then
            tx_enable_i  <= '1';
            rx_enable_i  <= '1';
            loopback_i   <= '1';
            m_axis_tready <= '1';

            s_axis_tdata  <= x"A5";
            s_axis_tvalid <= '1';
            wait until s_axis_tready = '1';
            wait until rising_edge(clk);
            s_axis_tvalid <= '0';

            wait until m_axis_tvalid = '1' for 1000 * C_CLK_PERIOD;
            check_equal(m_axis_tvalid, '1',
                "loopback: m_axis_tvalid should assert after RX completes");
            check_equal(m_axis_tdata, std_logic_vector'(x"A5"),
                "loopback: received byte mismatch");
            check_equal(m_axis_tlast, '1',
                "loopback: m_axis_tlast must always be '1' alongside tvalid (UART = one byte per packet)");
        end if;

        -- ── test_rx_byte ─────────────────────────────────────────────────────
        -- Drive a byte on the uart_rx_i pin and check the AXI-Stream output.
        -- m_axis_tready is intentionally left '0' until after tvalid is
        -- observed; asserting it early would consume the byte on the same
        -- clock it is published, causing the wait to miss the one-cycle pulse.
        if run("test_rx_byte") then
            rx_enable_i <= '1';

            uart_rx_send(x"C3");

            wait until m_axis_tvalid = '1' for 500 * C_CLK_PERIOD;
            check_equal(m_axis_tvalid, '1',
                "rx_byte: m_axis_tvalid should assert after receiving frame");
            check_equal(m_axis_tdata, std_logic_vector'(x"C3"),
                "rx_byte: received byte mismatch");
            m_axis_tready <= '1';
            wait_clk(1);
        end if;

        -- ── test_tx_busy ─────────────────────────────────────────────────────
        -- tx_busy_o should be low when idle, high during a frame, low after stop.
        if run("test_tx_busy") then
            tx_enable_i <= '1';
            check_equal(tx_busy_o, '0', "tx_busy should be low before any transmission");

            s_axis_tdata  <= x"FF";
            s_axis_tvalid <= '1';

            wait until tx_busy_o = '1' for 200 * C_CLK_PERIOD;
            check_equal(tx_busy_o, '1', "tx_busy should go high once TX starts");
            s_axis_tvalid <= '0';

            wait until tx_busy_o = '0' for 1200 * C_CLK_PERIOD;
            check_equal(tx_busy_o, '0', "tx_busy should go low after stop bit");
        end if;

        -- ── test_rx_frame_error ──────────────────────────────────────────────
        -- A bad stop bit (0 instead of 1) should assert rx_frame_err_o for
        -- exactly one clock cycle.  The wait is started while the bad stop
        -- bit is still being held so the one-cycle pulse is not missed.
        if run("test_rx_frame_error") then
            rx_enable_i <= '1';

            uart_rx_i <= '0';               -- start bit
            wait_clk(C_BAUD_DIV);
            for b in 0 to C_DATA_W-1 loop
                uart_rx_i <= '1';           -- data bits (value irrelevant)
                wait_clk(C_BAUD_DIV);
            end loop;
            uart_rx_i <= '0';               -- bad stop bit — hold low and
            -- watch for the error pulse; it fires at the stop-bit midpoint
            wait until rx_frame_err_o = '1' for 500 * C_CLK_PERIOD;
            check_equal(rx_frame_err_o, '1',
                "rx_frame_error: should be asserted on bad stop bit");
            uart_rx_i <= '1';               -- restore idle
        end if;

        test_runner_cleanup(runner);
    end process main;

    -- Watchdog: fail if a test runs longer than 2 ms.
    test_runner_watchdog(runner, 2 ms);

end architecture bench;
