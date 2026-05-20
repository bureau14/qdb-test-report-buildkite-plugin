#!/usr/bin/env python3
"""Build the vendored UI and refresh the Python HTML template."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[1]
UI_DIR = REPO_ROOT / "ui" / "report-ui"
DIST_HTML = UI_DIR / "dist" / "index.html"
TEMPLATE = REPO_ROOT / "tools" / "templates" / "report-template.html"
PLACEHOLDER = "<!-- TEST_REPORT_DATA -->"
INIT_SCRIPT_TAGS = (
    '<script src="./init.js"></script>',
    '<script src="/init.js"></script>',
)


def run(command: List[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def refresh_template() -> Path:
    run(["npm", "ci"], UI_DIR)
    run(["npm", "run", "build"], UI_DIR)

    html = DIST_HTML.read_text(encoding="utf-8")
    for script_tag in INIT_SCRIPT_TAGS:
        if script_tag in html:
            html = html.replace(script_tag, PLACEHOLDER, 1)
            break
    else:
        raise RuntimeError("Could not find init.js script tag in built HTML")

    count = html.count(PLACEHOLDER)
    if count != 1:
        raise RuntimeError(f"Expected exactly one {PLACEHOLDER} placeholder, found {count}")

    TEMPLATE.parent.mkdir(parents=True, exist_ok=True)
    TEMPLATE.write_text(html, encoding="utf-8")
    return TEMPLATE


def main() -> int:
    template = refresh_template()
    print(f"Wrote {template} ({template.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
