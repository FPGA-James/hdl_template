-- uart_rx.vhd
--
-- UART receiver: 8N1 serial input → AXI4-Stream master.
--
-- ── Oversampling principle ────────────────────────────────────────────────────
--
-- The receiver uses 16x oversampling to achieve noise-immune bit sampling.
-- An internal sample-rate generator fires sample_tick at baud_rate × 16.
-- Each baud period is therefore divided into 16 equal sample slots.
--
-- Start-bit detection is level-sensitive: a low on rx_i in the IDLE state
-- triggers a move to the START state.  The start bit is then verified at its
-- midpoint (sample slot C_RX_OVERSAMPLE/2 = 8) to reject glitches shorter
-- than half a baud period.
--
-- Each subsequent data and stop bit is sampled at its midpoint (sample slot
-- C_RX_OVERSAMPLE-1 = 15, counting from the end of the previous sample
-- window).
--
-- ── Bit-sampling diagram ──────────────────────────────────────────────────────
--
--  One baud period = 16 sample ticks
--
--  sample slot:  0  1  2  3  4  5  6  7 [8] 9 10 11 12 13 14 15
--  (start bit)   |--falling edge detected                      |
--                |---count to 8 in START state-->[verify here]  |
--
--  sample slot:  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14[15]
--  (data bits)   |-- previous bit boundary                 [sample]|
--
-- ── AXI4-Stream interface ─────────────────────────────────────────────────────
--
-- m_axis_tvalid is held asserted after a complete frame until m_axis_tready is
-- observed.  m_axis_tlast is always '1' alongside tvalid because each UART byte
-- is an independent, atomic packet — there are no multi-byte bursts at the
-- physical layer.
--
-- ── Error and overflow handling ───────────────────────────────────────────────
--
-- rx_frame_err_o — pulsed for one clock cycle when the stop bit is sampled as 0.
--                  The partially-assembled byte is discarded.
-- rx_overflow_o  — pulsed for one clock cycle when a new frame completes while
--                  m_axis_tvalid is still high (i.e. the previous byte was not
--                  consumed).  The new byte is discarded.
--
-- Instantiated by: uart_core

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library work;
use work.uart_pkg.all;

entity uart_rx is
    port (
        -- System clock, rising-edge triggered.
        clk            : in  std_logic;
        -- Synchronous active-low reset. Returns to IDLE and clears the output register.
        rst_n          : in  std_logic;

        -- ── Configuration ────────────────────────────────────────────────────
        -- Assert to enable the deserialiser.  Deassert to hold in reset.
        enable_i       : in  std_logic;
        -- Baud-rate divisor shared with the transmitter.
        -- The sample rate = baud_div_i / C_RX_OVERSAMPLE (clamped to 1 minimum).
        baud_div_i     : in  integer range 2 to 65535;

        -- ── Serial input ──────────────────────────────────────────────────────
        -- UART serial input line.  Idle-high.  Feed the loopback mux output here.
        rx_i           : in  std_logic;

        -- ── AXI4-Stream master ────────────────────────────────────────────────
        -- Received byte. Stable from the cycle tvalid asserts until tready is seen.
        m_axis_tdata   : out std_logic_vector(C_DATA_W-1 downto 0);
        -- Asserted when tdata holds a valid received byte. Held until tready.
        m_axis_tvalid  : out std_logic;
        -- Assert to consume the current byte and deassert tvalid.
        m_axis_tready  : in  std_logic;
        -- Always '1' when tvalid is asserted: each UART byte is its own packet.
        m_axis_tlast   : out std_logic;

        -- ── Status (one-clock-cycle pulses) ───────────────────────────────────
        -- Stop bit sampled as 0; received byte is discarded.
        rx_frame_err_o : out std_logic;
        -- Frame completed while tvalid was still high; new byte is discarded.
        rx_overflow_o  : out std_logic
    );
end entity uart_rx;

architecture rtl of uart_rx is

    -- ── 16x oversampling generator ────────────────────────────────────────────
    -- sample_tick fires at  clk_freq / (baud_div_i / C_RX_OVERSAMPLE).
    -- The period is rounded down (integer division) and clamped to 1.
    signal sample_ctr  : integer range 0 to 4095 := 0;
    signal sample_tick : std_logic := '0';

    -- ── RX state machine ──────────────────────────────────────────────────────
    -- IDLE  — waiting for a falling edge on rx_i (start of start bit).
    -- START — counting C_RX_OVERSAMPLE/2 sample ticks to reach the midpoint of
    --         the start bit, then verifying it is still low.
    -- DATA  — sampling C_DATA_W data bits, one per C_RX_OVERSAMPLE sample ticks.
    --         Bits are shifted into the MSB of rx_shift so that after C_DATA_W
    --         shifts the byte is correctly ordered: D0 in bit-0, D7 in bit-7.
    -- STOP  — sampling the stop bit at its midpoint.  A '1' publishes the byte;
    --         a '0' triggers the frame-error pulse.
    --
    -- State transitions (triggered by sample_tick when enable_i='1'):
    --
    --   +------+  rx_i='0'        +-------+  cnt=OVERSAMPLE/2 & rx_i='0'
    --   | IDLE | ---------------> | START | ────────────────────────────────>──+
    --   |      | <─glitch abort── |       | cnt=OVERSAMPLE/2 & rx_i='1'        |
    --   +------+                  +-------+                                     |
    --      ^                                                                     v
    --      |  cnt=C_RX_SAMPLE_POINT  +------+  cnt=C_RX_SAMPLE_POINT       +------+
    --      +<────────────────────────| STOP | <──────────────── (×C_DATA_W) | DATA |
    --                                +------+                                +------+
    type t_rx_state is (IDLE, START, DATA, STOP);
    signal rx_state      : t_rx_state := IDLE;
    signal next_state    : t_rx_state := IDLE;
    signal rx_shift      : std_logic_vector(C_DATA_W-1 downto 0) := (others => '0');
    signal rx_bit_cnt    : integer range 0 to C_DATA_W-1 := 0;
    signal rx_sample_cnt : integer range 0 to C_RX_OVERSAMPLE-1 := 0;

    -- Output register
    signal rx_data_r     : std_logic_vector(C_DATA_W-1 downto 0) := (others => '0');
    signal rx_valid_r    : std_logic := '0';

begin

    -- ── Sample-rate generator ─────────────────────────────────────────────────
    -- Produces sample_tick at 16x the baud rate.
    --
    -- .. wavedrom::
    --
    --    { "signal": [
    --      { "name": "rx_i",          "wave": "1.....0.................................1......." },
    --      { "name": "sample_tick",   "wave": "010101010101010101010101010101010101010101010101" },
    --      {},
    --      { "name": "state",
    --        "wave": "=.....=.................=...............................=.=......",
    --        "data": ["IDLE", "START (8 ticks to mid)", "DATA (16 ticks × 8 bits)", "STOP", "IDLE"] },
    --      {},
    --      { "name": "m_axis_tdata",  "wave": "x...........................................=....", "data": ["byte"] },
    --      { "name": "m_axis_tvalid", "wave": "0...........................................1...." },
    --      { "name": "m_axis_tlast",  "wave": "0...........................................1...." }
    --    ],
    --    "head": { "text": "RX 16x oversampling. Each column = 1 sample tick (baud_period/16)." } }
    p_sample : process(clk) is
        variable period : integer;
    begin
        if rising_edge(clk) then
            if rst_n = '0' or enable_i = '0' then
                sample_ctr  <= 0;
                sample_tick <= '0';
            else
                period := baud_div_i / C_RX_OVERSAMPLE;
                if period < 1 then
                    period := 1;
                end if;
                sample_tick <= '0';
                if sample_ctr = 0 then
                    sample_tick <= '1';
                    sample_ctr  <= period - 1;
                else
                    sample_ctr <= sample_ctr - 1;
                end if;
            end if;
        end if;
    end process p_sample;

    -- ── RX next-state logic (combinatorial) ──────────────────────────────────
    -- Computes next_state from current state and sample-synchronous inputs.
    -- State advances only when enable_i='1' and sample_tick='1'; otherwise holds.
    -- Transitions:
    --   IDLE  → START  when rx_i = '0'                              (start bit detected)
    --   START → DATA   when rx_sample_cnt = C_RX_OVERSAMPLE/2 and rx_i = '0'  (confirmed)
    --   START → IDLE   when rx_sample_cnt = C_RX_OVERSAMPLE/2 and rx_i = '1'  (glitch)
    --   DATA  → STOP   when rx_sample_cnt = C_RX_SAMPLE_POINT and rx_bit_cnt = C_DATA_LAST
    --   STOP  → IDLE   when rx_sample_cnt = C_RX_SAMPLE_POINT                  (always)
    p_rx_ns : process(rx_state, sample_tick, enable_i, rx_i, rx_sample_cnt, rx_bit_cnt) is
    begin
        next_state <= rx_state;                 -- default: hold current state
        if enable_i = '1' and sample_tick = '1' then
            case rx_state is

                when IDLE =>
                    if rx_i = '0' then
                        next_state <= START;
                    end if;

                when START =>
                    -- Two separate if blocks so the extractor captures both branches.
                    if rx_sample_cnt = C_RX_OVERSAMPLE / 2 and rx_i = '0' then
                        next_state <= DATA;     -- start bit confirmed
                    end if;
                    if rx_sample_cnt = C_RX_OVERSAMPLE / 2 and rx_i = '1' then
                        next_state <= IDLE;     -- glitch: abort
                    end if;

                when DATA =>
                    if rx_sample_cnt = C_RX_SAMPLE_POINT and rx_bit_cnt = C_DATA_LAST then
                        next_state <= STOP;
                    end if;

                when STOP =>
                    if rx_sample_cnt = C_RX_SAMPLE_POINT then
                        next_state <= IDLE;
                    end if;

            end case;
        end if;
    end process p_rx_ns;

    -- ── RX datapath + state register (sequential) ────────────────────────────
    -- Registers next_state on every rising edge.
    -- Datapath: sample counter, bit counter, shift register, output register.
    -- Advances on every sample_tick (16× per baud period).
    p_rx : process(clk) is
    begin
        if rising_edge(clk) then
            if rst_n = '0' or enable_i = '0' then
                rx_state       <= IDLE;
                rx_shift       <= (others => '0');
                rx_bit_cnt     <= 0;
                rx_sample_cnt  <= 0;
                rx_valid_r     <= '0';
                rx_frame_err_o <= '0';
                rx_overflow_o  <= '0';
            else
                rx_state <= next_state;         -- register next-state

                -- Clear one-cycle status strobes every clock cycle.
                rx_frame_err_o <= '0';
                rx_overflow_o  <= '0';

                -- Downstream consumed the output byte: deassert tvalid.
                if m_axis_tready = '1' and rx_valid_r = '1' then
                    rx_valid_r <= '0';
                end if;

                if sample_tick = '1' then
                    case rx_state is

                        when IDLE =>
                            -- Detect start-bit falling edge (level-sensitive).
                            if rx_i = '0' then
                                rx_sample_cnt <= 1;
                            end if;

                        when START =>
                            -- Count to the midpoint of the start bit and verify.
                            -- Midpoint = C_RX_OVERSAMPLE/2 = 8 sample ticks from
                            -- the first detected low.
                            if rx_sample_cnt = C_RX_OVERSAMPLE / 2 then
                                -- next_state already set by p_rx_ns (DATA or IDLE).
                                rx_sample_cnt <= 0;
                                rx_bit_cnt    <= 0;
                            else
                                rx_sample_cnt <= rx_sample_cnt + 1;
                            end if;

                        when DATA =>
                            -- Sample each data bit at its midpoint (C_RX_SAMPLE_POINT).
                            --
                            -- Bit-order reconstruction:
                            --   rx_i & rx_shift(C_DATA_W-1 downto 1) shifts the
                            --   incoming serial bit into the MSB each time, while
                            --   all previous bits shift right by one position.
                            --   After C_DATA_W iterations: D0 is in bit-0, D7 in bit-7.
                            if rx_sample_cnt = C_RX_SAMPLE_POINT then
                                rx_sample_cnt <= 0;
                                rx_shift <= rx_i & rx_shift(C_DATA_W-1 downto 1);
                                if rx_bit_cnt = C_DATA_LAST then
                                    rx_bit_cnt <= 0;
                                else
                                    rx_bit_cnt <= rx_bit_cnt + 1;
                                end if;
                            else
                                rx_sample_cnt <= rx_sample_cnt + 1;
                            end if;

                        when STOP =>
                            -- Sample the stop bit at its midpoint (C_RX_SAMPLE_POINT).
                            if rx_sample_cnt = C_RX_SAMPLE_POINT then
                                rx_sample_cnt <= 0;
                                if rx_i = '1' then
                                    -- Valid stop bit: publish received byte.
                                    if rx_valid_r = '1' then
                                        -- Previous byte not yet consumed: overflow.
                                        rx_overflow_o <= '1';
                                    else
                                        rx_data_r  <= rx_shift;
                                        rx_valid_r <= '1';
                                    end if;
                                else
                                    -- Bad stop bit: discard and flag.
                                    rx_frame_err_o <= '1';
                                end if;
                            else
                                rx_sample_cnt <= rx_sample_cnt + 1;
                            end if;

                    end case;
                end if;
            end if;
        end if;
    end process p_rx;

    m_axis_tdata  <= rx_data_r;
    m_axis_tvalid <= rx_valid_r;
    -- tlast is always coincident with tvalid: every UART byte is its own packet.
    m_axis_tlast  <= rx_valid_r;

end architecture rtl;
