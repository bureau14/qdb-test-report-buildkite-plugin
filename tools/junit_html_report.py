#!/usr/bin/env python3
"""Generate a self-contained HTML report directly from JUnit XML."""

from __future__ import annotations
from typing import List, Optional, Tuple, Union

import argparse
import json
from pathlib import Path
import sys

from html_report_writer import DEFAULT_TEMPLATE, write_html_report
from junit_report_model import build_report, format_counts, parse_platform_arg
from report_data import report_to_report_ui_data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate self-contained HTML from JUnit XML files"
    )
    parser.add_argument("--title", required=True, help="Report title/root node name")
    parser.add_argument(
        "--platform",
        action="append",
        type=parse_platform_arg,
        required=True,
        help="Platform input in name=path form. May be repeated.",
    )
    parser.add_argument("--output", required=True, type=Path, help="Output HTML file")
    parser.add_argument("--summary-json", type=Path, help="Output summary JSON file")
    parser.add_argument(
        "--template", type=Path, default=DEFAULT_TEMPLATE, help="HTML template path"
    )
    parser.add_argument(
        "--execution-name",
        help="Top-level report execution name; defaults to the report title",
    )
    parser.add_argument("--build-url", help="Buildkite build URL metadata")
    parser.add_argument(
        "--only-failures",
        action="store_true",
        help="Skip SUCCESSFUL and SKIPPED tests in the report tree; summary still shows full counts",
    )
    parser.add_argument(
        "--fail-on-status",
        choices=["failed", "errored", "never"],
        default="failed",
        help="Exit with code 64 if the report status matches these criteria (default: failed). Use 'never' to disable.",
    )
    return parser


def generate_html_report(
    *,
    title: str,
    platform_specs: List[Tuple[str, Union[Path, str]]],
    output: Path,
    summary_json: Optional[Path] = None,
    template: Path = DEFAULT_TEMPLATE,
    execution_name: Optional[str] = None,
    build_url: Optional[str] = None,
    only_failures: bool = False,
    fail_on_status: str = "failed",
) -> int:
    report = build_report(
        title=title,
        platform_specs=platform_specs,
        build_url=build_url,
    )
    data = report_to_report_ui_data(
        report, execution_name=execution_name, only_failures=only_failures
    )
    output_path = write_html_report(data, output, template)
    print(f"INFO  Wrote HTML report output={output_path} bytes={output_path.stat().st_size}", file=sys.stderr)

    if summary_json:
        summary = {
            "raw_testcases": report.raw_testcases,
            "suites": len(report.suites),
            "logical_tests": report.logical_test_count,
            "platform_executions": report.platform_execution_count,
            "targets": len(report.platforms),
            "status_counts": dict(report.status_counts),
            "root_status": report.root_status,
        }
        summary_json.parent.mkdir(parents=True, exist_ok=True)
        summary_json.write_text(json.dumps(summary, indent=2))
        print(f"INFO  Wrote summary JSON output={summary_json}", file=sys.stderr)

    print(
        f"INFO  Final summary: raw_testcases={report.raw_testcases} suites={len(report.suites)} "
        f"logical_tests={report.logical_test_count} platform_executions={report.platform_execution_count} "
        f"status_counts={format_counts(report.status_counts)} root_status={report.root_status}",
        file=sys.stderr,
    )

    if fail_on_status != "never" and report.root_status == fail_on_status.upper():
        print(f"INFO  Exiting with status {report.root_status} (code 64)", file=sys.stderr)
        return 64

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return generate_html_report(
            title=args.title,
            platform_specs=args.platform,
            output=args.output,
            summary_json=args.summary_json,
            template=args.template,
            execution_name=args.execution_name,
            build_url=args.build_url,
            only_failures=args.only_failures,
            fail_on_status=args.fail_on_status,
        )
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
