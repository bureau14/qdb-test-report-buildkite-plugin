#!/usr/bin/env python3
"""Generate a self-contained HTML report directly from JUnit XML."""

from __future__ import annotations

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
    parser.add_argument("--commit", help="Commit SHA metadata")
    parser.add_argument("--branch", help="Branch metadata")
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = build_report(
            title=args.title,
            platform_specs=args.platform,
            build_url=args.build_url,
            commit=args.commit,
            branch=args.branch,
        )
        data = report_to_report_ui_data(
            report, execution_name=args.execution_name, only_failures=args.only_failures
        )
        output = write_html_report(data, args.output, args.template)
        print(f"INFO  Wrote HTML report output={output} bytes={output.stat().st_size}", file=sys.stderr)

        if args.summary_json:
            summary = {
                "raw_testcases": report.raw_testcases,
                "suites": len(report.suites),
                "logical_tests": report.logical_test_count,
                "platform_executions": report.platform_execution_count,
                "targets": len(report.platforms),
                "status_counts": dict(report.status_counts),
                "root_status": report.root_status,
            }
            args.summary_json.parent.mkdir(parents=True, exist_ok=True)
            args.summary_json.write_text(json.dumps(summary, indent=2))
            print(f"INFO  Wrote summary JSON output={args.summary_json}", file=sys.stderr)

        print(
            f"INFO  Final summary: raw_testcases={report.raw_testcases} suites={len(report.suites)} "
            f"logical_tests={report.logical_test_count} platform_executions={report.platform_execution_count} "
            f"status_counts={format_counts(report.status_counts)} root_status={report.root_status}",
            file=sys.stderr,
        )

        if args.fail_on_status != "never" and report.root_status == args.fail_on_status.upper():
            print(f"INFO  Exiting with status {report.root_status} (code 64)", file=sys.stderr)
            return 64

    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
