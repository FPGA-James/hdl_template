-- uart_pkg.vhd
-- Project-level constants and shared type definitions for the UART module.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

package uart_pkg is

  -- Data width for UART frames (fixed 8-bit, 8N1 format)
  constant C_DATA_W : natural := 8;

  -- Default baud divisor: 100 MHz / 115200 ≈ 868
  constant C_BAUD_DIV_DEFAULT : natural := 868;

  -- RX oversampling factor (samples per baud period)
  constant C_RX_OVERSAMPLE : natural := 16;

  -- Derived sampling constants.
  -- Pre-computed so FSM transition conditions stay arithmetic-operator-free,
  -- which lets the hdl_autodoc FSM extractor parse them correctly.
  constant C_RX_SAMPLE_POINT : natural := C_RX_OVERSAMPLE - 1;  -- = 15 (data/stop midpoint)
  constant C_DATA_LAST       : natural := C_DATA_W - 1;          -- = 7  (last data bit index)

end package uart_pkg;
