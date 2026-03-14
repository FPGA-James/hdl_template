"""
test_generate_rst.py
--------------------
Tests for generate_rst.py.

Covers:
  - module_index_rst toctree contains the expected page entries (entity, fsm,
    timing, cdc, processes) and omits optional entries when not applicable.
  - entity_rst uses vhdl:autoentity for VHDL and literalinclude for SV.
  - cdc_rst returns a placeholder when no extracted file exists, and an
    include directive when the extracted file is present.
  - fsm_rst returns a placeholder when no extracted file exists, and an
    include directive when present.
  - write_if_missing does not overwrite an existing file.
  - write_always overwrites an existing file.
"""

from pathlib import Path

import pytest

from generate_rst import (
    cdc_rst,
    entity_rst,
    fsm_rst,
    module_index_rst,
    write_always,
    write_if_missing,
)


# ─────────────────────────────────────────────────────────────────────────────
# module_index_rst
# ─────────────────────────────────────────────────────────────────────────────

def _make_entity(name="my_mod", filename="my_mod.vhd"):
    return {"name": name, "brief": "A test module.", "file": filename, "ports": []}


def test_index_rst_contains_core_pages():
    """The module toctree always includes entity, fsm, timing, and cdc."""
    rst = module_index_rst(_make_entity(), children=[], shared_children=set())
    assert "entity" in rst
    assert "fsm" in rst
    assert "timing" in rst
    assert "cdc" in rst


def test_index_rst_includes_processes_when_present():
    """processes/index is added to the toctree when has_processes=True."""
    rst = module_index_rst(_make_entity(), children=[], shared_children=set(),
                           has_processes=True)
    assert "processes/index" in rst


def test_index_rst_omits_processes_when_absent():
    """processes/index is NOT added to the toctree when has_processes=False."""
    rst = module_index_rst(_make_entity(), children=[], shared_children=set(),
                           has_processes=False)
    assert "processes/index" not in rst


def test_index_rst_includes_submodules_section():
    """A 'Submodules' section is added when the module has children."""
    rst = module_index_rst(_make_entity(), children=["child_a", "child_b"],
                           shared_children=set())
    assert "Submodules" in rst
    assert "../child_a/index" in rst


def test_index_rst_no_submodules_section_when_childless():
    """No 'Submodules' section is emitted for a leaf module."""
    rst = module_index_rst(_make_entity(), children=[], shared_children=set())
    assert "Submodules" not in rst


def test_index_rst_top_includes_registers():
    """The top-level module's toctree includes the registers page."""
    rst = module_index_rst(_make_entity(), children=[], shared_children=set(),
                           is_top=True)
    assert "registers" in rst


# ─────────────────────────────────────────────────────────────────────────────
# entity_rst
# ─────────────────────────────────────────────────────────────────────────────

def test_entity_rst_vhdl_uses_autoentity():
    """VHDL entity pages use the vhdl:autoentity directive."""
    entity = _make_entity(filename="my_mod.vhd")
    rst = entity_rst(entity)
    assert "vhdl:autoentity" in rst


def test_entity_rst_sv_uses_literalinclude():
    """SystemVerilog entity pages use literalinclude (no sphinx-vhdl support for SV)."""
    entity = _make_entity(filename="my_mod.sv")
    rst = entity_rst(entity)
    assert "literalinclude" in rst
    assert "vhdl:autoentity" not in rst


def test_entity_rst_contains_source_filename():
    """The entity page mentions the HDL source filename."""
    entity = _make_entity(filename="counter.vhd")
    rst = entity_rst(entity)
    assert "counter.vhd" in rst


# ─────────────────────────────────────────────────────────────────────────────
# cdc_rst
# ─────────────────────────────────────────────────────────────────────────────

def test_cdc_rst_placeholder_when_no_extracted_file(tmp_path):
    """A 'pending' placeholder is returned when no *_cdc.rst file exists."""
    entity = _make_entity()
    rst = cdc_rst(entity, module_dir=tmp_path)
    assert "pending" in rst.lower() or "make extract" in rst


def test_cdc_rst_include_when_extracted_file_exists(tmp_path):
    """An include directive is returned when the extracted *_cdc.rst file exists."""
    entity = _make_entity(name="my_mod")
    (tmp_path / "my_mod_cdc.rst").write_text("CDC content here.\n")
    rst = cdc_rst(entity, module_dir=tmp_path)
    assert ".. include::" in rst
    assert "my_mod_cdc.rst" in rst


# ─────────────────────────────────────────────────────────────────────────────
# fsm_rst
# ─────────────────────────────────────────────────────────────────────────────

def test_fsm_rst_placeholder_when_no_extracted_file(tmp_path):
    """A 'no FSM detected' placeholder is returned when no extracted FSM file exists."""
    entity = _make_entity()
    rst = fsm_rst(entity, module_dir=tmp_path)
    assert "No FSM" in rst or "no FSM" in rst.lower()


def test_fsm_rst_include_when_extracted_file_exists(tmp_path):
    """An include directive is returned when the extracted FSM rst file exists."""
    entity = _make_entity(name="my_mod")
    (tmp_path / "my_mod.rst").write_text("FSM content here.\n")
    rst = fsm_rst(entity, module_dir=tmp_path)
    assert ".. include::" in rst
    assert "my_mod.rst" in rst


# ─────────────────────────────────────────────────────────────────────────────
# File write helpers
# ─────────────────────────────────────────────────────────────────────────────

def test_write_if_missing_creates_file(tmp_path):
    """write_if_missing creates the file when it does not already exist."""
    p = tmp_path / "new.rst"
    write_if_missing(p, "content")
    assert p.read_text() == "content"


def test_write_if_missing_does_not_overwrite(tmp_path):
    """write_if_missing leaves an existing file untouched."""
    p = tmp_path / "existing.rst"
    p.write_text("original")
    write_if_missing(p, "new content")
    assert p.read_text() == "original"


def test_write_always_overwrites_existing(tmp_path):
    """write_always replaces an existing file with the new content."""
    p = tmp_path / "regen.rst"
    p.write_text("old content")
    write_always(p, "new content")
    assert p.read_text() == "new content"


def test_write_always_creates_parent_dirs(tmp_path):
    """write_always creates any missing parent directories."""
    p = tmp_path / "deep" / "nested" / "file.rst"
    write_always(p, "content")
    assert p.exists()
