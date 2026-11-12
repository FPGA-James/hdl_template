"""Pytest collection guard.

Pre-init (the raw template) the test files here hold the template's placeholder
in their import lines, which is a SyntaxError, so pytest -- which pytest.ini
points at tb/cocotb -- must not collect them until `make init` has substituted
the project name. The placeholder is built from pieces so that `make init` does
not rewrite this check.
"""

from pathlib import Path

_PLACEHOLDER = "<<" + "NAME" + ">>"
_probe = Path(__file__).with_name("test_NAME_regs.py")

collect_ignore_glob = ["test_*.py"] if _PLACEHOLDER in _probe.read_text() else []
