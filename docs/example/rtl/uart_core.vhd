-- uart_core.vhd
--
-- UART core: structural wrapper instantiating uart_tx and uart_rx.
--
-- ── Hierarchy ─────────────────────────────────────────────────────────────────
--
--   uart_core
--     ├── uart_tx  — baud-rate generator + 8N1 TX state machine
--     │              AXI4-Stream slave  →  serial TX line
--     └── uart_rx  — 16x oversampling generator + RX state machine
--                    serial RX line  →  AXI4-Stream master
--
-- ── Loopback ──────────────────────────────────────────────────────────────────
--
-- When loopback_i is asserted the TX serial output is routed back into the RX
-- serial input via a combinatorial mux.  The physical uart_rx_i pin is ignored
-- during loopback.  uart_tx_o still drives the physical pin so an oscilloscope
-- can observe the transmitted data.
--
-- Loopback is useful for:
--   • self-test without external hardware
--   • baud-rate verification (compare TX output with RX recovered data)
--
-- ── Register interface ────────────────────────────────────────────────────────
--
-- All configuration and status signals are forwarded to/from the sub-modules
-- unchanged.  See uart_tx and uart_rx for per-signal documentation.
--
-- Instantiated by: uart_top

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library work;
use work.uart_pkg.all;

entity uart_core is
    port (
        -- System clock, rising-edge triggered.
        clk             : in  std_logic;
        -- Synchronous active-low reset.
        rst_n           : in  std_logic;

        -- ── Register interface ────────────────────────────────────────────────
        tx_enable_i     : in  std_logic;
        rx_enable_i     : in  std_logic;
        -- Assert to connect tx_o back to rx_i internally (loopback self-test).
        loopback_i      : in  std_logic;
        -- Baud divisor shared by TX and RX. baud_rate = clk_freq / baud_div_i.
        baud_div_i      : in  integer range 2 to 65535;

        -- Asserted while TX is serialising a frame (start + data + stop bits).
        tx_busy_o       : out std_logic;
        -- One-cycle pulse: stop bit received as 0 (frame error in RX).
        rx_frame_err_o  : out std_logic;
        -- One-cycle pulse: RX completed a frame before the previous byte was read.
        rx_overflow_o   : out std_logic;

        -- ── AXI4-Stream TX slave ──────────────────────────────────────────────
        s_axis_tdata    : in  std_logic_vector(C_DATA_W-1 downto 0);
        s_axis_tvalid   : in  std_logic;
        s_axis_tready   : out std_logic;
        -- End-of-packet for AXI4-Stream compliance. No effect on 8N1 serialiser.
        s_axis_tlast    : in  std_logic;

        -- ── AXI4-Stream RX master ─────────────────────────────────────────────
        m_axis_tdata    : out std_logic_vector(C_DATA_W-1 downto 0);
        m_axis_tvalid   : out std_logic;
        m_axis_tready   : in  std_logic;
        -- Always '1' with tvalid: each received byte is an independent packet.
        m_axis_tlast    : out std_logic;

        -- ── Physical UART pins ────────────────────────────────────────────────
        -- TX serial output line.  Driven regardless of loopback setting.
        uart_tx_o       : out std_logic;
        -- RX serial input line.  Ignored when loopback_i is asserted.
        uart_rx_i       : in  std_logic
    );
end entity uart_core;

architecture rtl of uart_core is

    -- TX serial output (before loopback mux, after uart_tx)
    signal tx_serial : std_logic;

    -- RX serial input after loopback mux
    signal rx_serial : std_logic;

begin

    -- ── Loopback mux ─────────────────────────────────────────────────────────
    -- Combinatorial: routes tx_serial to the RX input when loopback is enabled.
    -- uart_tx_o is driven unconditionally so the physical pin always reflects
    -- the TX state (useful for monitoring with a logic analyser during loopback).
    rx_serial <= tx_serial when loopback_i = '1' else uart_rx_i;
    uart_tx_o <= tx_serial;

    -- ── TX sub-module ─────────────────────────────────────────────────────────
    -- Baud-rate generator + 8N1 serialiser.
    -- See uart_tx.vhd for detailed timing documentation.
    u_tx : entity work.uart_tx
        port map (
            clk           => clk,
            rst_n         => rst_n,
            enable_i      => tx_enable_i,
            baud_div_i    => baud_div_i,
            s_axis_tdata  => s_axis_tdata,
            s_axis_tvalid => s_axis_tvalid,
            s_axis_tready => s_axis_tready,
            s_axis_tlast  => s_axis_tlast,
            tx_busy_o     => tx_busy_o,
            tx_o          => tx_serial
        );

    -- ── RX sub-module ─────────────────────────────────────────────────────────
    -- 16x oversampling generator + deserialiser.
    -- See uart_rx.vhd for detailed timing documentation.
    u_rx : entity work.uart_rx
        port map (
            clk            => clk,
            rst_n          => rst_n,
            enable_i       => rx_enable_i,
            baud_div_i     => baud_div_i,
            rx_i           => rx_serial,
            m_axis_tdata   => m_axis_tdata,
            m_axis_tvalid  => m_axis_tvalid,
            m_axis_tready  => m_axis_tready,
            m_axis_tlast   => m_axis_tlast,
            rx_frame_err_o => rx_frame_err_o,
            rx_overflow_o  => rx_overflow_o
        );

end architecture rtl;
