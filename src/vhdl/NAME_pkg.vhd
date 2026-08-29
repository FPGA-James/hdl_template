-- =============================================================================
-- Company      : <company>
--
-- Designer     : <name>
--
-- Filename     : <<NAME>>_pkg.vhd
--
-- Purpose      : Shared constants and types for the <<NAME>> design hierarchy.
--
-- Tools        : <simulators/frameworks used to verify this, e.g. GHDL + VUnit>
--
-- References   :
--   - <datasheet / spec / paper / issue link>
--
-- Date Created : YYYY-MM-DD
--
-- Date Updated : YYYY-MM-DD
-- =============================================================================
--
-- Revision History
-- =============================================================================
-- Date        Author          Description
-- ----------  --------------  --------------------------------------------
-- YYYY-MM-DD  <name>          Initial creation
-- =============================================================================

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- <<NAME>> package.
--
-- Shared constants and types for the <<NAME>> design hierarchy.
-- Include this package in all entities within the <<NAME>> module.
package <<NAME>>_pkg is

    -- Width of the pulse counter output in bits.
    constant C_COUNT_W : natural := 16;

end package <<NAME>>_pkg;
