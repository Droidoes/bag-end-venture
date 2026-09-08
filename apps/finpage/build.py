#!/usr/bin/env python3
"""Finpage build — inlines the shared shell/core plus every registered page
into one single-file HTML artifact (apps/finpage/BagEnd.html).

Method only: sources carry no financial values; the built file is committed.
Add a capability = add a page module + a registry entry, then rebuild.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
OUT = HERE / "BagEnd.html"


def main() -> None:
    shell = (SRC / "shell.html").read_text()
    css = (SRC / "core.css").read_text()
    core = (SRC / "core.js").read_text()
    pages = json.loads((SRC / "pages.json").read_text())

    page_js = []
    for p in pages:
        mod = (SRC / p["file"]).read_text()
        page_js.append(f"/* page: {p['id']} */\n{mod}")
    pages_block = "\n\n".join(page_js)

    out = (shell
           .replace("{{CORE_CSS}}", css)
           .replace("{{CORE_JS}}", core)
           .replace("{{PAGES_JS}}", pages_block))
    OUT.write_text(out)
    # sanity: every registered id has a page module and a nav entry target
    for p in pages:
        assert f'id: "{p["id"]}"' in out, f"missing module for {p['id']}"
    print(f"built {OUT} ({len(out.splitlines())} lines, {len(pages)} pages: "
          f"{', '.join(p['id'] for p in pages)})")


if __name__ == "__main__":
    main()
