"""
conftest.py
-----------
Adds the scripts/hdl_autodoc directory to sys.path so that each test file
can import the pipeline modules directly (e.g. `from parse_hierarchy import ...`).
"""

import sys
from pathlib import Path

# scripts/hdl_autodoc/ is the parent of this tests/ directory
sys.path.insert(0, str(Path(__file__).parent.parent))
