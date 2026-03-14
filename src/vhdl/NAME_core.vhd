library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library work;
use work.<<NAME>>_pkg.all;

-- <<NAME>> core.
--
-- Parameterisable pulse counter. Counts input pulses when enabled and
-- reports the running total via the status register interface.
--
-- Register interface:
--   enable_i      -- from conf register; enables counting
--   increment_i   -- from conf register; step size per pulse (1..255)
--   reset_count_i -- from command register; one-cycle pulse clears count
--   enabled_o     -- to status register; high when counter is active
--   pulse_count_o -- to status register; current count value
--
-- Instantiated by: <<NAME>>_top
entity <<NAME>>_core is
    port (
        -- System clock, rising-edge triggered.
        clk           : in  std_logic;
        -- Synchronous active-low reset. Clears count and status outputs.
        rst_n         : in  std_logic;

        -- ── From register block ──────────────────────────────────────────────
        -- Enable counting when asserted.
        enable_i      : in  std_logic;
        -- Step size added to the count on each qualifying pulse.
        increment_i   : in  integer range 1 to 255;
        -- One-cycle reset pulse. Clears count_r to zero on the next clock.
        reset_count_i : in  std_logic;

        -- ── To register block ────────────────────────────────────────────────
        -- Asserted whenever enable_i is high and counting is not in reset.
        enabled_o     : out std_logic;
        -- Running pulse count, saturates at (2**C_COUNT_W)-1.
        pulse_count_o : out std_logic_vector(C_COUNT_W-1 downto 0)
    );
end entity <<NAME>>_core;

-- RTL implementation using a 2-process clocked style.
architecture rtl of <<NAME>>_core is

    -- Registered pulse counter. Saturates rather than wrapping.
    signal count_r : unsigned(C_COUNT_W-1 downto 0) := (others => '0');

begin

    -- p_count: Clocked pulse counter with saturating addition.
    --
    -- Priority:  reset > reset_count_i > counting
    -- Saturation prevents wrap-around at full-scale.
    --
    -- .. wavedrom::
    --
    --    { "signal": [
    --      { "name": "clk",          "wave": "P........." },
    --      { "name": "rst_n",        "wave": "0.1......." },
    --      { "name": "enable_i",     "wave": "0..1......" },
    --      { "name": "pulse_i",      "wave": "0...1.1..." },
    --      { "name": "reset_count_i","wave": "0......10." },
    --      { "name": "count_r",      "wave": "=..=.==.=.", "data": ["0","0","1","2","0"] },
    --      { "name": "enabled_o",    "wave": "0..1......" }
    --    ]}
    p_count : process(clk) is
        variable next_count : unsigned(C_COUNT_W downto 0);
    begin
        if rising_edge(clk) then
            if rst_n = '0' then
                count_r   <= (others => '0');
                enabled_o <= '0';
            elsif reset_count_i = '1' then
                count_r   <= (others => '0');
                enabled_o <= enable_i;
            elsif enable_i = '1' then
                -- Saturating add: promote to C_COUNT_W+1 bits, cap at all-ones.
                next_count := ('0' & count_r) + to_unsigned(increment_i, C_COUNT_W + 1);
                if next_count(C_COUNT_W) = '1' then
                    count_r <= (others => '1');
                else
                    count_r <= next_count(C_COUNT_W-1 downto 0);
                end if;
                enabled_o <= '1';
            else
                enabled_o <= '0';
            end if;
        end if;
    end process p_count;

    pulse_count_o <= std_logic_vector(count_r);

end architecture rtl;
