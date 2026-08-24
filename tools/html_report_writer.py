#!/usr/bin/env python3
"""Write self-contained HTML reports from report UI data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PLACEHOLDER = "<!-- TEST_REPORT_DATA -->"
DEFAULT_TEMPLATE = Path(__file__).resolve().parent / "templates" / "report-template.html"


def dumps_embedded_json(data: Any) -> str:
    """Serialize JSON for safe embedding in <script type=application/json>."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # Prevent embedded data from terminating the script tag or creating HTML parsing hazards.
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_html(data: Any, template_path: Path | str = DEFAULT_TEMPLATE) -> str:
    template = Path(template_path).read_text(encoding="utf-8")
    placeholder_count = template.count(PLACEHOLDER)
    if placeholder_count != 1:
        raise ValueError(
            f"Expected exactly one {PLACEHOLDER} placeholder, found {placeholder_count}"
        )
    script = (
        f'<script id="report-data" type="application/json">{dumps_embedded_json(data)}</script>'
    )
    return template.replace(PLACEHOLDER, script)


def write_html_report(
    data: Any,
    output: Path | str,
    template_path: Path | str = DEFAULT_TEMPLATE,
) -> Path:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_html(data, template_path), encoding="utf-8")
    return output_path
