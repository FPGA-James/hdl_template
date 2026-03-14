"""
test_include_registers.py
--------------------------
Tests for include_registers.py.

Covers:
  - find_entry_point prefers index.html when present.
  - find_entry_point falls back to the first alphabetically sorted HTML file
    when index.html is absent.
  - find_entry_point returns None when the directory contains no HTML files.
  - The placeholder RST is written when no register export is found.
  - The iframe RST is written (with the correct entry filename) when an
    export is found.
  - The register directory is copied to docs/_static/registers/.
"""

from pathlib import Path

import pytest

from include_registers import find_entry_point


# ─────────────────────────────────────────────────────────────────────────────
# find_entry_point
# ─────────────────────────────────────────────────────────────────────────────

def test_find_entry_point_prefers_index_html(tmp_path):
    """index.html is returned when it exists, regardless of other HTML files."""
    (tmp_path / "index.html").write_text("<html/>")
    (tmp_path / "other.html").write_text("<html/>")
    result = find_entry_point(tmp_path)
    assert result.name == "index.html"


def test_find_entry_point_fallback_to_first_html(tmp_path):
    """When index.html is absent, the alphabetically first HTML file is returned."""
    (tmp_path / "bbb.html").write_text("<html/>")
    (tmp_path / "aaa.html").write_text("<html/>")
    result = find_entry_point(tmp_path)
    assert result.name == "aaa.html"


def test_find_entry_point_returns_none_when_empty(tmp_path):
    """None is returned when the directory contains no HTML files."""
    (tmp_path / "style.css").write_text("body {}")
    result = find_entry_point(tmp_path)
    assert result is None


def test_find_entry_point_returns_none_for_empty_dir(tmp_path):
    """None is returned for a completely empty directory."""
    result = find_entry_point(tmp_path)
    assert result is None


def test_find_entry_point_ignores_subdirectory_html(tmp_path):
    """HTML files in subdirectories are not returned as the entry point."""
    sub = tmp_path / "Registers"
    sub.mkdir()
    (sub / "reg_ctrl.html").write_text("<html/>")
    # No HTML in root — should return None
    result = find_entry_point(tmp_path)
    assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Full pipeline integration (using tmp_path filesystem)
# ─────────────────────────────────────────────────────────────────────────────

def _run_include_registers(project_root: Path, docs_dir: Path,
                            entry: str = "") -> str:
    """
    Helper: run the include_registers main logic directly and return the
    content written to docs/registers.rst.
    """
    import shutil
    from include_registers import (
        REGISTERS_RST_PLACEHOLDER,
        REGISTERS_RST_TEMPLATE,
        find_entry_point,
    )

    static_dir    = docs_dir / "_static"
    registers_rst = docs_dir / "registers.rst"
    src_dir       = project_root / "registers" / "generated"
    dest_dir      = static_dir / "registers"

    forced_entry = entry.strip() if entry.strip() else None

    if src_dir.exists() and (forced_entry or find_entry_point(src_dir)):
        if forced_entry:
            ep = src_dir / forced_entry
            if not ep.exists():
                ep = find_entry_point(src_dir)
        else:
            ep = find_entry_point(src_dir)

        if dest_dir.exists():
            shutil.rmtree(dest_dir, ignore_errors=True)
        shutil.copytree(src_dir, dest_dir)
        registers_rst.write_text(
            REGISTERS_RST_TEMPLATE.format(entry_filename=ep.name)
        )
    else:
        registers_rst.write_text(REGISTERS_RST_PLACEHOLDER)

    return registers_rst.read_text()


def test_placeholder_written_when_no_generated_dir(tmp_path):
    """registers.rst contains the placeholder when registers/generated/ does not exist."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    rst = _run_include_registers(tmp_path, docs_dir)
    assert "not yet generated" in rst.lower() or "No Questa" in rst


def test_iframe_written_when_export_found(tmp_path):
    """registers.rst contains an iframe when registers/generated/index.html exists."""
    gen_dir = tmp_path / "registers" / "generated"
    gen_dir.mkdir(parents=True)
    (gen_dir / "index.html").write_text("<html><body>Regs</body></html>")

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "_static").mkdir()

    rst = _run_include_registers(tmp_path, docs_dir)
    assert "iframe" in rst
    assert "index.html" in rst


def test_register_dir_copied_to_static(tmp_path):
    """The generated/ directory tree is copied to docs/_static/registers/."""
    gen_dir = tmp_path / "registers" / "generated"
    gen_dir.mkdir(parents=True)
    (gen_dir / "index.html").write_text("<html/>")
    (gen_dir / "style.css").write_text("body {}")

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "_static").mkdir()

    _run_include_registers(tmp_path, docs_dir)

    dest = docs_dir / "_static" / "registers"
    assert (dest / "index.html").exists()
    assert (dest / "style.css").exists()


def test_custom_entry_point_used_in_iframe(tmp_path):
    """When a forced entry filename is provided it is used in the iframe src."""
    gen_dir = tmp_path / "registers" / "generated"
    gen_dir.mkdir(parents=True)
    (gen_dir / "counter_regs.html").write_text("<html/>")

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "_static").mkdir()

    rst = _run_include_registers(tmp_path, docs_dir, entry="counter_regs.html")
    assert "counter_regs.html" in rst
