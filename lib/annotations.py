from __future__ import annotations
import subprocess
import sys


def build_annotation_body(title: str, summary: dict, html_url: str) -> str:
    """
    Builds the markdown body for the Buildkite annotation.
    """
    counts = summary.get("status_counts", {})
    failed = counts.get("FAILED", 0)
    errored = counts.get("ERRORED", 0)
    skipped = counts.get("SKIPPED", 0)
    passed = counts.get("SUCCESSFUL", 0)

    logical_tests = summary.get("logical_tests", 0)
    targets = len(summary.get("resolved_platforms", []))
    if targets == 0:
        targets = summary.get("targets", 1)

    parts = []
    parts.append(f"{logical_tests} tests")
    if targets > 1:
        parts.append(f"{targets} targets")

    parts.append(f"{passed} passed")
    parts.append(f"{failed} failed")
    parts.append(f"{errored} errored")
    parts.append(f"{skipped} skipped")

    stats_line = ", ".join(parts)
    warnings = summary.get("warnings", [])

    body = f"## {title}\n\n{stats_line}"
    if warnings:
        warning_lines = "\n".join(f"- {warning}" for warning in warnings)
        body += f"\n\n⚠️ Warnings\n\n{warning_lines}"
    body += f'\n\n<a href="{html_url}" target="_blank" rel="noopener noreferrer">Open full report</a>'
    return body


def get_annotation_style(summary: dict) -> str:
    """
    Determines the annotation style (success, warning, error, info).
    """
    root_status = summary.get("root_status", "INFO")
    counts = summary.get("status_counts", {})
    failed = counts.get("FAILED", 0)
    errored = counts.get("ERRORED", 0)

    if failed > 0 or errored > 0 or root_status in ("FAILED", "ERRORED"):
        return "error"

    if summary.get("warnings"):
        return "warning"

    # Skips are treated as success.
    if root_status == "SUCCESSFUL":
        return "success"

    return "info"


def create_buildkite_annotation(
    body: str, context: str, style: str, priority: int, scope: str = "build"
):
    """
    Calls buildkite-agent annotate to create the annotation.
    """
    args = [
        "buildkite-agent",
        "annotate",
        body,
        "--context",
        context,
        "--style",
        style,
        "--priority",
        str(priority),
    ]
    if scope == "job":
        args.append("--scope")
        args.append("job")

    try:
        subprocess.run(args, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"WARNING: failed to create Buildkite annotation: {exc}", file=sys.stderr)
