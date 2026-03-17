-- uart_tx.vhd
--
-- UART transmitter: AXI4-Stream slave → 8N1 serial output.
--
-- ── Frame format ──────────────────────────────────────────────────────────────
--
--   Idle  START  D0  D1  D2  D3  D4  D5  D6  D7  STOP  Idle
--    1     0    lsb                             msb  1    1
--
-- Each bit occupies exactly baud_div_i clock cycles.  The line is held high
-- (marking idle) when not transmitting.
--
-- ── AXI4-Stream interface ─────────────────────────────────────────────────────
--
-- The transmitter acts as an AXI4-Stream slave.  Because UART has no
-- sub-byte granularity, every byte is a complete and independent frame:
--   s_axis_tlast — accepted for protocol compliance; UART always frames one
--                  byte at a time so tlast has no effect on serialisation.
--
-- tready is asserted for a single clock cycle at the baud_tick boundary when:
--   (a) the transmitter is idle, AND
--   (b) enable_i is asserted, AND
--   (c) s_axis_tvalid is asserted.
-- The upstream master must hold tvalid stable until it observes tready.
--
-- ── Throughput ────────────────────────────────────────────────────────────────
--
-- Maximum throughput = baud_rate / 10  (one 10-bit frame per byte).
-- At 115200 baud: 11520 bytes/sec.
--
-- ── Register interface ────────────────────────────────────────────────────────
--
-- enable_i   — deassert to hold TX line idle and prevent new frames.
--              An in-progress frame is abandoned and the line returns high.
-- baud_div_i — must not change during an active frame; changes take effect at
--              the start of the next frame.
--
-- Instantiated by: uart_core

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library work;
use work.uart_pkg.all;

entity uart_tx is
    port (
        -- System clock, rising-edge triggered.
        clk           : in  std_logic;
        -- Synchronous active-low reset. Aborts any active frame, returns TX line high.
        rst_n         : in  std_logic;

        -- ── Configuration ────────────────────────────────────────────────────
        -- Assert to enable the serialiser.  Deassert to hold the line idle.
        enable_i      : in  std_logic;
        -- Baud-rate divisor.  baud_rate = clk_freq / baud_div_i.
        -- Example: 868 → 115200 baud at 100 MHz.  Minimum value: 2.
        baud_div_i    : in  integer range 2 to 65535;

        -- ── AXI4-Stream slave ─────────────────────────────────────────────────
        -- Byte to transmit.
        s_axis_tdata  : in  std_logic_vector(C_DATA_W-1 downto 0);
        -- Data valid: upstream asserts when tdata holds a valid byte.
        s_axis_tvalid : in  std_logic;
        -- Data ready: pulsed high for one cycle when this byte is accepted.
        s_axis_tready : out std_logic;
        -- End of packet: accepted for AXI4-Stream compliance; no behavioural effect
        -- on the serialiser (each UART byte is always its own complete frame).
        s_axis_tlast  : in  std_logic;

        -- ── Status ────────────────────────────────────────────────────────────
        -- Asserted from the start bit through to and including the stop bit.
        -- Returns low on the baud_tick immediately after the stop bit.
        tx_busy_o     : out std_logic;

        -- ── Serial output ─────────────────────────────────────────────────────
        -- UART serial output line. Idle-high.
        tx_o          : out std_logic
    );
end entity uart_tx;

architecture rtl of uart_tx is

    -- ── Baud generator ────────────────────────────────────────────────────────
    -- Counts down from baud_div_i-1 to 0, firing baud_tick on the terminal count.
    -- One baud_tick pulse = exactly one bit period (baud_div_i clock cycles).
    signal baud_ctr  : integer range 0 to 65535 := 0;
    signal baud_tick : std_logic := '0';

    -- ── TX state machine ──────────────────────────────────────────────────────
    -- IDLE    : line held high; accepts a new byte on the next baud_tick when
    --           enable_i and s_axis_tvalid are both asserted.
    -- SENDING : serialising the current byte.
    --           tx_bit_cnt 0..C_DATA_W-1 : index of the next data bit to emit.
    --           tx_bit_cnt = C_DATA_W    : stop bit phase.
    --
    -- State transitions (all triggered on baud_tick when enable_i='1'):
    --
    --   +-------+  s_axis_tvalid='1'  +----------+
    --   | IDLE  | ------------------> | SENDING  |
    --   |  tx=1 | <------------------ | tx=frame |
    --   +-------+  tx_bit_cnt=C_DATA_W+----------+
    --               (stop bit sent)
    type t_tx_state is (IDLE, SENDING);
    signal tx_state   : t_tx_state := IDLE;
    signal next_state : t_tx_state := IDLE;
    signal tx_shift   : std_logic_vector(C_DATA_W-1 downto 0) := (others => '0');
    signal tx_bit_cnt : integer range 0 to C_DATA_W := 0;
    signal tx_out_r   : std_logic := '1';

begin

    -- ── Baud generator ───────────────────────────────────────────────────────
    -- baud_tick fires once every baud_div_i clock cycles.
    -- The counter reloads from the live baud_div_i register each period, so
    -- divisor changes take effect at the next baud_tick.
    p_baud : process(clk) is
    begin
        if rising_edge(clk) then
            if rst_n = '0' then
                baud_ctr  <= 0;
                baud_tick <= '0';
            else
                baud_tick <= '0';
                if baud_ctr = 0 then
                    baud_tick <= '1';
                    baud_ctr  <= baud_div_i - 1;
                else
                    baud_ctr <= baud_ctr - 1;
                end if;
            end if;
        end if;
    end process p_baud;

    -- ── TX next-state logic (combinatorial) ──────────────────────────────────
    -- Computes next_state from the current state and baud-synchronous inputs.
    -- State advances only when enable_i='1' and baud_tick='1'; otherwise holds.
    -- Transitions:
    --   IDLE    → SENDING  when s_axis_tvalid = '1'  (byte accepted)
    --   SENDING → IDLE     when tx_bit_cnt = C_DATA_W (stop bit complete)
    p_tx_ns : process(tx_state, baud_tick, enable_i, s_axis_tvalid, tx_bit_cnt) is
    begin
        next_state <= tx_state;                 -- default: hold current state
        if enable_i = '1' and baud_tick = '1' then
            case tx_state is

                when IDLE =>
                    if s_axis_tvalid = '1' then
                        next_state <= SENDING;
                    end if;

                when SENDING =>
                    if tx_bit_cnt = C_DATA_W then
                        next_state <= IDLE;
                    end if;

            end case;
        end if;
    end process p_tx_ns;

    -- ── TX datapath + state register (sequential) ────────────────────────────
    -- Registers next_state on every rising edge.
    -- Datapath: shift register, bit counter, serial output, tx_busy status.
    -- Each frame: START(0) | D0..D7 LSB-first | STOP(1). Total = 10 bit periods.
    --
    -- .. wavedrom::
    --
    --    { "signal": [
    --      { "name": "baud_tick",     "wave": "10.10.10.10.10.10.10.10.10.10.10" },
    --      { "name": "tvalid",        "wave": "1...0..........................." },
    --      { "name": "tready",        "wave": "010............................." },
    --      { "name": "tlast",         "wave": "1...0..........................." },
    --      {},
    --      { "name": "tx_busy_o",     "wave": "0...1...................0......." },
    --      { "name": "tx_o",          "wave": "1...0.1.0.1.0.1.0.1.0.1.1.....",
    --        "data": ["START","D0","D1","D2","D3","D4","D5","D6","D7","STOP"] }
    --    ],
    --    "head": { "text": "8N1 frame (0x55 shown). Each pair of columns = one baud period." } }
    p_tx : process(clk) is
    begin
        if rising_edge(clk) then
            if rst_n = '0' or enable_i = '0' then
                tx_state   <= IDLE;
                tx_out_r   <= '1';
                tx_bit_cnt <= 0;
                tx_busy_o  <= '0';
            else
                tx_state <= next_state;         -- register next-state
                if baud_tick = '1' then
                    case tx_state is

                        when IDLE =>
                            tx_out_r  <= '1';
                            tx_busy_o <= '0';
                            if s_axis_tvalid = '1' then
                                -- Latch data, emit start bit, enter SENDING.
                                -- s_axis_tlast is accepted for AXI4-Stream
                                -- compliance but does not alter serialisation.
                                tx_shift   <= s_axis_tdata;
                                tx_out_r   <= '0';      -- start bit
                                tx_bit_cnt <= 0;
                                tx_busy_o  <= '1';
                            end if;

                        when SENDING =>
                            if tx_bit_cnt < C_DATA_W then
                                -- Emit data bits D0..D7, LSB first.
                                tx_out_r   <= tx_shift(0);
                                tx_shift   <= '0' & tx_shift(C_DATA_W-1 downto 1);
                                tx_bit_cnt <= tx_bit_cnt + 1;
                            else
                                -- Stop bit (tx_bit_cnt = C_DATA_W = 8).
                                tx_out_r   <= '1';
                                tx_busy_o  <= '0';
                                tx_bit_cnt <= 0;
                            end if;

                    end case;
                end if;
            end if;
        end if;
    end process p_tx;

    -- tready pulses for exactly one clock cycle (the baud_tick where the byte
    -- is latched).  The upstream master must hold tvalid until tready is seen.
    s_axis_tready <= '1' when (tx_state = IDLE and enable_i = '1'
                                and baud_tick = '1' and s_axis_tvalid = '1') else '0';

    tx_o <= tx_out_r;

    -- Suppress unused-input warning: s_axis_tlast is accepted for AXI4-Stream
    -- protocol compliance but has no effect on the 8N1 serialiser.
    -- synthesis translate_off
    -- pragma coverage off
    assert s_axis_tlast = s_axis_tlast report "tlast unused in uart_tx" severity note;
    -- pragma coverage on
    -- synthesis translate_on

end architecture rtl;
