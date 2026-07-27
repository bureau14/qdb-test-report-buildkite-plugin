#!/usr/bin/env python3
"""Generate a self-contained HTML report directly from JUnit XML."""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple, Union

import argparse
import json
from pathlib import Path
import sys

from html_report_writer import DEFAULT_TEMPLATE, write_html_report
from junit_report_model import ArtifactLink, build_report, format_counts, parse_platform_arg
from report_data import report_to_report_ui_data


def log(message: str) -> None:
    print(f"INFO  {message}", file=sys.stderr)


def warn(message: str) -> None:
    print(f"WARN  {message}", file=sys.stderr)


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
    parser.add_argument("--commit-url", help="Git commit URL metadata")
    parser.add_argument(
        "--only-failures",
        action="store_true",
        help="Skip SUCCESSFUL and SKIPPED tests in the report tree; summary still shows full counts",
    )
    parser.add_argument(
        "--fail-on-test-failures",
        action="store_true",
        help="Exit with code 64 if any test failed or errored.",
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
    commit_url: Optional[str] = None,
    source_job_id: Optional[str] = None,
    source_artifacts_by_job_id: Optional[Dict[str, List[ArtifactLink]]] = None,
    artifacts: Optional[List[ArtifactLink]] = None,
    artifact_metadata: Optional[List[Dict[str, Any]]] = None,
    xml_source_links: Optional[Dict[Path, Optional[str]]] = None,
    only_failures: bool = False,
    fail_on_test_failures: bool = False,
) -> int:
    report = build_report(
        title=title,
        platform_specs=platform_specs,
        build_url=build_url,
        commit_url=commit_url,
        source_job_id=source_job_id,
        source_artifacts_by_job_id=source_artifacts_by_job_id,
        artifacts=artifacts,
        xml_source_links=xml_source_links,
    )
    data = report_to_report_ui_data(
        report, execution_name=execution_name, only_failures=only_failures
    )
    output_path = write_html_report(data, output, template)
    log(
        f"Wrote HTML report output={output_path} bytes={output_path.stat().st_size}",
    )

    if summary_json:
        summary = {
            "raw_testcases": report.raw_testcases,
            "suites": len(report.suites),
            "logical_tests": report.logical_test_count,
            "platform_executions": report.platform_execution_count,
            "targets": len(report.platforms),
            "platforms": report.platforms,
            "resolved_platforms": report.resolved_platforms,
            "status_counts": dict(report.status_counts),
            "logical_status_counts": dict(report.logical_status_counts),
            "root_status": report.root_status,
            "malformed_junit_xml": report.malformed_junit_xml,
        }
        if artifact_metadata is not None:
            summary["artifacts"] = artifact_metadata
        summary_json.parent.mkdir(parents=True, exist_ok=True)
        summary_json.write_text(json.dumps(summary, indent=2))
        log(f"Wrote summary JSON output={summary_json}")

    log(
        f"Final summary: raw_testcases={report.raw_testcases} suites={len(report.suites)} "
        f"logical_tests={report.logical_test_count} platform_executions={report.platform_execution_count} "
        f"status_counts={format_counts(report.status_counts)} root_status={report.root_status}",
    )

    failed_or_errored = report.status_counts["FAILED"] + report.status_counts["ERRORED"]
    if fail_on_test_failures and failed_or_errored:
        log(
            f"Exiting with {failed_or_errored} failed/errored test execution(s) (code 64)",
        )
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
            commit_url=args.commit_url,
            only_failures=args.only_failures,
            fail_on_test_failures=args.fail_on_test_failures,
        )
    except Exception as exc:  # pragma: no cover - CLI guard
        warn(f"error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
