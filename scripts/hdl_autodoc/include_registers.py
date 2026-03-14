#!/usr/bin/env python3
"""
include_registers.py
--------------------
Looks for a Questa Register Assistant export at:
    <project_root>/registers/generated/

Expected structure (Questa Register Assistant output):
    generated/
    ├── index.html              ← entry point
    ├── index2.html
    ├── index_registers.html
    ├── style.css
    └── Registers/
        ├── <reg_block>.html
        └── ...

If found:
  - Copies the entire directory tree to docs/_static/registers/
  - Writes docs/registers.rst embedding index.html in a full-screen iframe

If not found:
  - Writes docs/registers.rst with a clear "not yet generated" notice

Always writes docs/registers.rst so the toctree entry never breaks.

Usage:
    python scripts/include_registers.py <project_root> <docs_dir>
"""

import shutil
import sys
from pathlib import Path


REGISTERS_RST_PLACEHOLDER = """\
Registers
=========

.. admonition:: Register map not yet generated
   :class: warning

   No Questa Register Assistant export was found at ``registers/generated/``.

   To generate it, run Register Assistant and export HTML output, then
   re-run ``make html``.

   Expected location::

       registers/
       └── generated/
           ├── index.html
           ├── index2.html
           ├── index_registers.html
           ├── style.css
           └── Registers/
               └── <register_block>.html

"""

REGISTERS_RST_TEMPLATE = """\
Registers
=========

.. raw:: html

   <style>
     /* Remove content area padding so iframe butts up cleanly */
     .wy-nav-content {{
       max-width: 100% !important;
       padding: 0 !important;
     }}
     .document, .documentwrapper, .bodywrapper, .body, section {{
       height: 100%;
       margin: 0 !important;
       padding: 0 !important;
     }}
     /* Fixed iframe that starts exactly where the sidebar ends.
        RTD sidebar is 300px wide. Top bar is ~60px.
        JS below reads the actual sidebar width at runtime for robustness. */
     #registers-frame {{
       position: fixed;
       top: 60px;
       left: 300px;
       width: calc(100vw - 300px);
       height: calc(100vh - 60px);
       border: none;
       z-index: 100;
     }}
     /* Floating info strip — sits above the iframe, clear of the sidebar */
     #reg-info {{
       position: fixed;
       bottom: 1.5rem;
       right: 1.5rem;
       z-index: 200;
       background: rgba(30, 30, 46, 0.82);
       color: #cdd6f4;
       font-family: 'IBM Plex Mono', monospace;
       font-size: 0.78em;
       padding: 0.4rem 1rem;
       border-radius: 2rem;
       border: 1px solid rgba(137, 180, 250, 0.3);
       backdrop-filter: blur(8px);
       pointer-events: none;
       white-space: nowrap;
     }}
   </style>
   <script>
     // Measure the actual sidebar width at runtime so the iframe aligns
     // correctly if the user has resized or the theme has changed.
     document.addEventListener("DOMContentLoaded", function() {{
       var sidebar = document.querySelector(".wy-nav-side");
       var topbar  = document.querySelector(".wy-nav-top");
       var frame   = document.getElementById("registers-frame");
       if (sidebar && frame) {{
         var sw = sidebar.offsetWidth;
         var th = topbar ? topbar.offsetHeight : 60;
         frame.style.left   = sw + "px";
         frame.style.width  = "calc(100vw - " + sw + "px)";
         frame.style.top    = th + "px";
         frame.style.height = "calc(100vh - " + th + "px)";
       }}
     }});
   </script>
   <iframe
     id="registers-frame"
     src="_static/registers/{entry_filename}"
     title="Register Map">
   </iframe>
   <div id="reg-info">Register Map &mdash; re-run <code>make html</code> to update</div>

"""


def find_entry_point(src_dir: Path) -> Path | None:
    """
    Locate the Register Assistant entry point.
    Prefers index.html; falls back to the first HTML file in the root
    (not in Registers/ subdir) if index.html is absent.
    """
    preferred = src_dir / "index.html"
    if preferred.exists():
        return preferred

    # Fallback: first .html/.HTML in the root only
    candidates = [
        f for f in src_dir.iterdir()
        if f.is_file() and f.suffix.lower() == ".html"
    ]
    if candidates:
        candidates.sort()
        return candidates[0]

    return None


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("Usage: include_registers.py <project_root> <docs_dir> [entry_point]")

    project_root  = Path(sys.argv[1])
    docs_dir      = Path(sys.argv[2])
    # Optional: explicit entry point filename (e.g. "index.html", "counter_regs.html")
    forced_entry  = sys.argv[3].strip() if len(sys.argv) > 3 and sys.argv[3].strip() else None

    static_dir    = docs_dir / "_static"
    registers_rst = docs_dir / "registers.rst"

    src_dir  = project_root / "registers" / "generated"
    dest_dir = static_dir / "registers"

    if src_dir.exists() and (forced_entry or find_entry_point(src_dir)):
        # Use forced entry if provided, otherwise auto-detect
        if forced_entry:
            entry = src_dir / forced_entry
            if not entry.exists():
                print(f"  WARNING: REG_ENTRY={forced_entry!r} not found in {src_dir} "
                      f"— falling back to auto-detect")
                entry = find_entry_point(src_dir)
        else:
            entry = find_entry_point(src_dir)

        # Remove stale copy then copy the full tree.
        # ignore_errors=True avoids a race when html + pdf build in parallel.
        if dest_dir.exists():
            shutil.rmtree(dest_dir, ignore_errors=True)
        shutil.copytree(src_dir, dest_dir)

        # Count what was copied
        html_count = len(list(dest_dir.rglob("*.html"))) + \
                     len(list(dest_dir.rglob("*.HTML")))
        reg_dir    = dest_dir / "Registers"
        reg_count  = len(list(reg_dir.glob("*.html")) +
                         list(reg_dir.glob("*.HTML"))) if reg_dir.exists() else 0

        registers_rst.write_text(REGISTERS_RST_TEMPLATE.format(entry_filename=entry.name))

        print(f"  → registers: copied {src_dir.relative_to(project_root)} "
              f"({html_count} HTML files, {reg_count} register blocks)")
        print(f"  → entry point: {entry.name}")
        print(f"  → {registers_rst}")

    else:
        registers_rst.write_text(REGISTERS_RST_PLACEHOLDER)
        if src_dir.exists():
            print(f"  → registers: directory found but no HTML entry point detected")
        else:
            print(f"  → registers: no export found at registers/generated/ — writing placeholder")
        print(f"  → {registers_rst}")