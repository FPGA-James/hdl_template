-- =============================================================================
-- Company      : <company>
--
-- Designer     : <name>
--
-- Filename     : <filename>
--
-- Purpose      : <one-line description of what this entity does>
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

-- <ENTITY_NAME>.
--
-- <Longer description of behaviour, register interface, or protocol this
-- entity implements. This comment is picked up by sphinx-vhdl's
-- autoentity directive for the generated documentation page, so keep it
-- accurate and current.>
entity <ENTITY_NAME> is
    port (
        -- System clock, rising-edge triggered.
        clk   : in  std_logic;
        -- Synchronous active-low reset.
        rst_n : in  std_logic

        -- Add ports here.
    );
end entity <ENTITY_NAME>;

architecture rtl of <ENTITY_NAME> is

begin

end architecture rtl;
