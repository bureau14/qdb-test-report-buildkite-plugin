#!/usr/bin/env python3
"""Generate a self-contained HTML report directly from JUnit XML."""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any

from html_report_writer import DEFAULT_TEMPLATE, write_html_report
from junit_report_model import ArtifactLink, build_report, format_counts, parse_platform_arg
from report_data import report_to_report_ui_data
from report_logging import LOG_LEVELS, configure_logging, logger, trace


def log(message: str) -> None:
    logger.info(message)


def warn(message: str) -> None:
    logger.warning(message)


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
        "--log-level",
        choices=LOG_LEVELS,
        default="error",
        help="Minimum output severity (default: error)",
    )
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
    platform_specs: list[tuple[str, Path | str]],
    output: Path,
    summary_json: Path | None = None,
    template: Path = DEFAULT_TEMPLATE,
    execution_name: str | None = None,
    build_url: str | None = None,
    commit_url: str | None = None,
    source_job_id: str | None = None,
    source_artifacts_by_job_id: dict[str, list[ArtifactLink]] | None = None,
    artifacts: list[ArtifactLink] | None = None,
    artifact_metadata: list[dict[str, Any]] | None = None,
    xml_source_links: dict[Path, str | None] | None = None,
    only_failures: bool = False,
    fail_on_test_failures: bool = False,
    log_level: str = "error",
) -> int:
    configure_logging(log_level)
    started = time.monotonic()
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
    parsed = time.monotonic()
    log(f"Built JUnit report model in {parsed - started:.1f}s")
    data = report_to_report_ui_data(
        report, execution_name=execution_name, only_failures=only_failures
    )
    serialized = time.monotonic()
    log(f"Created HTML UI data in {serialized - parsed:.1f}s")
    output_path = write_html_report(data, output, template)
    if logger.isEnabledFor(logging.INFO):
        log(
            f"Wrote HTML report output={output_path} bytes={output_path.stat().st_size} "
            f"in {time.monotonic() - serialized:.1f}s",
        )

    if summary_json:
        with trace("report.summary"):
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
                "failed_test_cases": [
                    {
                        "suite": execution.suite_name,
                        "test_file": execution.test_file,
                        "test_case": (
                            execution.name
                            if execution.report_kind == "ctest"
                            else execution.logical_id
                        ),
                        "report_kind": execution.report_kind,
                        "platform": execution.platform,
                        "status": execution.status,
                        "reason": execution.reason,
                        "duration_seconds": execution.duration_seconds,
                        "source_xml_url": execution.source_xml_url,
                    }
                    for suite in report.suites.values()
                    for test_file in suite.test_files.values()
                    for logical in test_file.logical_tests.values()
                    for execution in logical.executions.values()
                    if execution.status in ("FAILED", "ERRORED")
                ],
            }
            if artifact_metadata is not None:
                summary["artifacts"] = artifact_metadata
            summary_json.parent.mkdir(parents=True, exist_ok=True)
            summary_json.write_text(json.dumps(summary, indent=2))
            log(f"Wrote summary JSON output={summary_json}")

    if logger.isEnabledFor(logging.INFO):
        log(
            f"Final summary: raw_testcases={report.raw_testcases} suites={len(report.suites)} "
            f"logical_tests={report.logical_test_count} platform_executions={report.platform_execution_count} "
            f"status_counts={format_counts(report.status_counts)} root_status={report.root_status}",
        )

    failed_or_errored = report.status_counts["FAILED"] + report.status_counts["ERRORED"]
    if fail_on_test_failures and failed_or_errored:
        logger.error(
            f"Exiting with {failed_or_errored} failed/errored test execution(s) (code 64)",
        )
        return 64

    return 0


def main(argv: list[str] | None = None) -> int:
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
            log_level=args.log_level,
        )
    except Exception as exc:  # noqa: BLE001 - CLI guard
        logger.fatal("Report generation failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
