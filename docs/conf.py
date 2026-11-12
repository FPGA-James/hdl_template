# conf.py — Sphinx configuration for the <<NAME>> documentation.
#
# Thin wrapper around HDL AutoDoc's shared configuration (submodules/HDLAutoDoc).
# The Makefile passes -c docs, so this file is the one Sphinx loads; it execs the
# tool's conf.py (theme, extensions, WaveDrom/Graphviz/LaTeX settings, all driven by
# the AUTODOC_* environment variables autodoc.mk sets, and the sphinx-vhdl
# incremental-build fix in its own setup()) and then adds the one project-specific
# difference below. Static assets and templates are read from the
# tool, not copied here.

import os
import sys

_tool_confdir = os.environ["AUTODOC_TOOL_CONFDIR"]
# The tool's conf imports helper modules that sit next to it (mermaid_support, v3.13+)
# using its own __file__, which is this wrapper's path once exec'd here.
sys.path.insert(0, _tool_confdir)
_tool_conf = os.path.join(_tool_confdir, "conf.py")
with open(_tool_conf, encoding="utf-8") as _f:
    exec(compile(_f.read(), _tool_conf, "exec"))

# ── Paths: tool assets first, then any project-local static files ────────────
_project_static = os.path.abspath(os.path.join(os.environ.get("AUTODOC_SOURCEDIR") or "docs", "_static"))
html_static_path = [os.path.join(_tool_confdir, "_static"), _project_static]
templates_path   = [os.path.join(_tool_confdir, "_templates")]
html_logo        = os.path.join(_tool_confdir, "_static", "logo.svg")
html_favicon     = html_logo

# ── Project additions to the tool's configuration ────────────────────────────
extensions += ["sphinxcontrib.rsvgconverter"]  # SVG → PDF conversion for LaTeX/PDF builds
