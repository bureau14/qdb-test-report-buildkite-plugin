from __future__ import annotations

import subprocess
import sys
from html import escape

MAX_ANNOTATION_BYTES = 1024 * 1024
MAX_FAILURE_REASON_CHARS = 240


def failed_test_table(summary: dict, available_bytes: int) -> str:
    cases = summary.get("failed_test_cases", [])
    if not cases:
        return ""

    headers = {
        "ctest": (
            "\n\n### Failed test cases — CTest\n\n"
            "| Status | Test case | Failure reason |\n"
            "| --- | --- | --- |\n"
        ),
        "test": (
            "\n\n### Failed test cases — Boost.Test / test-runner\n\n"
            "| Status | Suite::file | Test case | Failure reason |\n"
            "| --- | --- | --- | --- |\n"
        ),
    }

    def cell(value: str) -> str:
        # Encode Markdown punctuation too, so test names remain literal table cells.
        value = escape(" ".join(value.split()))
        for char in "\\|`*_[]~":
            value = value.replace(char, f"&#{ord(char)};")
        return value

    def omitted_notice(count: int) -> str:
        return f"\n\n{count} failed test execution(s) omitted due to the annotation size limit."

    def render_row(case: dict) -> str:
        cells = [cell(case.get("status", ""))]
        if case.get("report_kind") != "ctest":
            cells.append(cell(f"{case.get('suite', '')}::{case.get('test_file', '')}"))
        cells.append(cell(case.get("test_case", "")))
        reason = " ".join((case.get("reason") or "").split())
        if len(reason) > MAX_FAILURE_REASON_CHARS:
            reason = reason[: MAX_FAILURE_REASON_CHARS - 1] + "…"
        cells.append(cell(reason) if reason else "—")
        return "| " + " | ".join(cells) + " |\n"

    groups: dict[str, list[str]] = {kind: [] for kind in headers}
    for case in cases:
        kind = "ctest" if case.get("report_kind") == "ctest" else "test"
        groups[kind].append(render_row(case))
    full_table = "".join(headers[kind] + "".join(rows) for kind, rows in groups.items() if rows)
    if len(full_table.encode("utf-8")) <= available_bytes:
        return full_table

    parts = []
    size = 0
    shown = 0
    for kind, rows in groups.items():
        header = headers[kind]
        for row in rows:
            addition = header + row
            row_bytes = len(addition.encode("utf-8"))
            notice_bytes = len(omitted_notice(len(cases) - shown - 1).encode("utf-8"))
            if size + row_bytes + notice_bytes <= available_bytes:
                parts.append(addition)
                size += row_bytes
                shown += 1
                header = ""

    table = "".join(parts)
    omitted = len(cases) - shown
    if omitted:
        table += omitted_notice(omitted)
    return table if len(table.encode("utf-8")) <= available_bytes else ""


def get_annotation_warnings(summary: dict, scope: str = "build") -> list[str]:
    warnings = list(summary.get("warnings", []))

    targets = int(summary.get("targets", 0))
    platforms = summary.get("platforms") or []
    resolved_platforms = summary.get("resolved_platforms")
    if scope != "job" and resolved_platforms is not None and len(resolved_platforms) < targets:
        missing = targets - len(resolved_platforms)
        missing_platforms = [
            platform for platform in platforms if platform not in set(resolved_platforms)
        ]
        if missing_platforms:
            target_label = "target" if missing == 1 else "targets"
            warnings.append(
                f"No test executions for {missing} configured {target_label}: "
                f"{', '.join(missing_platforms)}."
            )
        else:
            warnings.append(
                f"{missing} of {targets} configured targets produced no test executions."
            )

    if scope == "job":
        counts = summary.get("logical_status_counts") or summary.get("status_counts", {})
        passed = int(counts.get("SUCCESSFUL", 0))
        logical_tests = int(summary.get("logical_tests", 0))
        if logical_tests == 0:
            warnings.append("This job report is empty: 0 tests produced no test executions.")
        elif passed == 0:
            warnings.append("This job report has 0 passing tests.")

    return warnings


def get_malformed_junit_xml(summary: dict) -> list[dict]:
    return list(summary.get("malformed_junit_xml", []))


def build_annotation_body(
    title: str, summary: dict, html_url: str | None, scope: str = "build"
) -> str:
    """
    Builds the markdown body for the Buildkite annotation.
    """
    counts = summary.get("logical_status_counts") or summary.get("status_counts", {})
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
    warnings = get_annotation_warnings(summary, scope=scope)

    body = f"## {title}\n\n{stats_line}"
    if warnings:
        warning_lines = "\n".join(f"- {warning}" for warning in warnings)
        body += f"\n\n⚠️ Warnings\n\n{warning_lines}"
    malformed_junit_xml = get_malformed_junit_xml(summary)
    if malformed_junit_xml:

        def malformed_line(item: dict) -> str:
            file = item.get("file", "<unknown>")
            platform = item.get("platform", "<unknown>")
            label = f"{file} ({platform})"
            if url := item.get("url"):
                label = f'<a href="{url}" target="_blank" rel="noopener noreferrer">{label}</a>'
            return f"- {label}: {item.get('error', 'invalid XML')}"

        malformed_lines = "\n".join(malformed_line(item) for item in malformed_junit_xml)
        body += f"\n\n❌ Malformed JUnit XML\n\n{malformed_lines}"
    if html_url:
        body += f'\n\n<a href="{html_url}" target="_blank" rel="noopener noreferrer">Open full report</a>'
    body += failed_test_table(summary, MAX_ANNOTATION_BYTES - len(body.encode("utf-8")))
    return body


def get_annotation_style(summary: dict) -> str:
    """
    Determines the annotation style (success, warning, error, info).
    """
    root_status = summary.get("root_status", "INFO")
    counts = summary.get("status_counts", {})
    failed = counts.get("FAILED", 0)
    errored = counts.get("ERRORED", 0)

    if (
        failed > 0
        or errored > 0
        or root_status in ("FAILED", "ERRORED")
        or get_malformed_junit_xml(summary)
    ):
        return "error"

    if get_annotation_warnings(summary):
        return "warning"

    # Skips are treated as success.
    if root_status == "SUCCESSFUL":
        return "success"

    return "info"


def get_job_annotation_style(summary: dict) -> str:
    """
    Determines the annotation style for job-scoped reports.
    """
    style = get_annotation_style(summary)
    if style == "error":
        return style

    counts = summary.get("logical_status_counts") or summary.get("status_counts", {})
    passed = int(counts.get("SUCCESSFUL", 0))
    logical_tests = int(summary.get("logical_tests", 0))
    if logical_tests == 0 or passed == 0:
        return "warning"

    return style


def create_buildkite_annotation(
    body: str, context: str, style: str, priority: int, scope: str = "build"
):
    """
    Calls buildkite-agent annotate to create the annotation.
    """
    args = [
        "buildkite-agent",
        "annotate",
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
        subprocess.run(args, input=body.encode("utf-8"), check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"WARNING: failed to create Buildkite annotation: {exc}", file=sys.stderr)
