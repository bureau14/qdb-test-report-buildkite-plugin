#!/usr/bin/env python3
"""Parse JUnit XML files into a neutral report model."""

from __future__ import annotations
from typing import List, Optional, Tuple, Union, Counter, OrderedDict
import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import glob
import re
import sys
import xml.etree.ElementTree as ET

STATUS_ORDER = ["SUCCESSFUL", "SKIPPED", "FAILED", "ERRORED"]
STATUS_SEVERITY = {"SUCCESSFUL": 0, "SKIPPED": 1, "FAILED": 2, "ERRORED": 3}

# Pattern to match Buildkite Job IDs (UUIDs). We strip these from test identities
# to support Buildkite parallelism: multiple jobs for the same variant can each
# upload their own JUnit XML without being treated as distinct tests in the report.
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def log_info(message: str) -> None:
    print(f"\tINFO  {message}", file=sys.stderr)


def log_warn(message: str) -> None:
    print(f"\tWARN  {message}", file=sys.stderr)


def format_counts(counter: Counter[str]) -> str:
    parts = [f"{status}={counter[status]}" for status in STATUS_ORDER if counter[status]]
    for key in sorted(counter):
        if key not in STATUS_ORDER and counter[key]:
            parts.append(f"{key}={counter[key]}")
    return ", ".join(parts) if parts else "none"


@dataclass
class TestcaseExecution:
    platform: str
    source_file: Path
    source_id: str
    suite_name: str
    classname: str
    name: str
    logical_id: str
    status: str
    duration_seconds: float
    reason: Optional[str] = None
    output: Optional[str] = None


@dataclass
class LogicalTest:
    suite_name: str
    logical_id: str
    classname: str
    name: str
    executions: "OrderedDict[str, TestcaseExecution]" = field(default_factory=OrderedDict)


@dataclass
class TestSuite:
    name: str
    logical_tests: "OrderedDict[str, LogicalTest]" = field(default_factory=OrderedDict)


@dataclass
class Report:
    title: str
    platforms: List[str]
    suites: "OrderedDict[str, TestSuite]"
    build_url: Optional[str] = None
    commit_url: Optional[str] = None
    generated_at: str = ""
    total_files: int = 0
    raw_testcases: int = 0
    duplicates_seen: int = 0
    duplicates_replaced: int = 0

    @property
    def resolved_platforms(self) -> List[str]:
        """Returns the list of platforms that actually had at least one test execution."""
        seen = set()
        for suite in self.suites.values():
            for logical in suite.logical_tests.values():
                for platform in logical.executions:
                    seen.add(platform)
        return [p for p in self.platforms if p in seen]

    @property
    def logical_test_count(self) -> int:
        return sum(len(suite.logical_tests) for suite in self.suites.values())

    @property
    def platform_execution_count(self) -> int:
        return sum(
            len(logical.executions)
            for suite in self.suites.values()
            for logical in suite.logical_tests.values()
        )

    @property
    def duration_seconds(self) -> float:
        return sum(
            execution.duration_seconds
            for suite in self.suites.values()
            for logical in suite.logical_tests.values()
            for execution in logical.executions.values()
        )

    @property
    def status_counts(self) -> Counter[str]:
        return Counter(
            execution.status
            for suite in self.suites.values()
            for logical in suite.logical_tests.values()
            for execution in logical.executions.values()
        )

    @property
    def logical_status_counts(self) -> Counter[str]:
        return Counter(
            logical_status(logical)
            for suite in self.suites.values()
            for logical in suite.logical_tests.values()
        )

    @property
    def root_status(self) -> str:
        return aggregate_status(list(self.status_counts.elements()))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def has_glob_magic(path: Union[Path, str]) -> bool:
    return any(char in str(path) for char in "*?[]")


def discover_xml_files(path: Union[Path, str]) -> List[Path]:
    """Return XML files for a file, directory, or glob, sorted deterministically."""
    input_path = Path(path)
    if has_glob_magic(input_path):
        return sorted(
            {
                Path(match).resolve()
                for match in glob.glob(str(input_path), recursive=True)
                if Path(match).is_file() and Path(match).suffix == ".xml"
            },
            key=lambda p: p.as_posix(),
        )
    if input_path.is_file():
        return [input_path]
    if input_path.is_dir():
        return sorted(
            (p for p in input_path.rglob("*.xml") if p.is_file()),
            key=lambda p: p.relative_to(input_path).as_posix(),
        )
    log_warn(f"JUnit path does not exist: {input_path}")
    return []


def parse_platform_arg(value: str) -> Tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("platform must use name=path format")
    name, raw_path = value.split("=", 1)
    if not name.strip():
        raise argparse.ArgumentTypeError("platform name cannot be empty")
    if not raw_path.strip():
        raise argparse.ArgumentTypeError("platform path cannot be empty")
    return name.strip(), Path(raw_path)


def logical_test_identity(testcase: ET.Element, source_id: str) -> Tuple[str, str, str]:
    name = testcase.attrib.get("name", "").strip() or "<unnamed>"
    classname = testcase.attrib.get("classname", "").strip()
    test_id = f"{classname}::{name}" if classname else name
    return test_id, classname, name


def testcase_status(testcase: ET.Element) -> str:
    if testcase.find("error") is not None:
        return "ERRORED"
    if testcase.find("failure") is not None:
        return "FAILED"
    if testcase.find("skipped") is not None:
        return "SKIPPED"
    return "SUCCESSFUL"


def specific_reason_from_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if line.startswith("- message:"):
            return line.removeprefix("- message:").strip()
    for line in lines:
        if line not in {"ASSERTION FAILURE:", "Failures detected in:"}:
            return line
    return lines[0] if lines else None


def testcase_reason_and_output(
    testcase: ET.Element, status: str
) -> Tuple[Optional[str], Optional[str]]:
    if status == "ERRORED":
        node = testcase.find("error")
    elif status == "FAILED":
        node = testcase.find("failure")
    elif status == "SKIPPED":
        node = testcase.find("skipped")
    else:
        node = None

    reason = None
    output_parts: List[str] = []
    if node is not None:
        raw_message = node.attrib.get("message")
        node_text = node.text.strip() if node.text and node.text.strip() else None
        if node_text:
            output_parts.append(node_text)
        if status == "SKIPPED" and raw_message:
            reason = raw_message
        elif raw_message and raw_message.lower() not in {"failure", "error"}:
            reason = raw_message
        else:
            reason = specific_reason_from_text(node_text) or raw_message or node.attrib.get("type")

    for output_name in ("system-out", "system-err"):
        output_node = testcase.find(output_name)
        if output_node is not None and output_node.text and output_node.text.strip():
            output_text = output_node.text.strip()
            output_parts.append(output_text)
            if reason is None and status == "SKIPPED":
                reason = output_text.splitlines()[0]

    return reason, "\n\n".join(output_parts) if output_parts else None


def duration_seconds(testcase: ET.Element) -> float:
    raw = testcase.attrib.get("time", "0")
    try:
        value = float(raw)
    except ValueError:
        return 0.0
    return max(value, 0.0)


def aggregate_status(statuses: List[str]) -> str:
    if any(status == "ERRORED" for status in statuses):
        return "ERRORED"
    if any(status == "FAILED" for status in statuses):
        return "FAILED"
    # Skips are treated as success for the purpose of the overall report status.
    return "SUCCESSFUL"


def logical_status(logical: LogicalTest) -> str:
    statuses = [execution.status for execution in logical.executions.values()]
    if any(status == "ERRORED" for status in statuses):
        return "ERRORED"
    if any(status == "FAILED" for status in statuses):
        return "FAILED"
    if statuses and all(status == "SKIPPED" for status in statuses):
        return "SKIPPED"
    return "SUCCESSFUL"


def worse_execution(current: TestcaseExecution, candidate: TestcaseExecution) -> TestcaseExecution:
    if STATUS_SEVERITY[candidate.status] > STATUS_SEVERITY[current.status]:
        return candidate
    return current


def local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def iter_junit_suites(root: ET.Element) -> List[ET.Element]:
    if local_name(root) == "testsuite":
        return [root]
    return [element for element in root.iter() if local_name(element) == "testsuite"]


def parse_junit_file(
    path: Path,
    platform: str,
    source_id: Optional[str] = None,
) -> List[TestcaseExecution]:
    if source_id is None:
        source_id = path.name
    if path.stat().st_size == 0:
        log_warn(f"skipping empty JUnit XML file file={path} platform={platform}")
        return []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        log_warn(f"skipping malformed JUnit XML file file={path} platform={platform} error={error}")
        return []
    executions: List[TestcaseExecution] = []
    suites = iter_junit_suites(root)
    if not suites:
        log_warn(f"no testsuite elements found file={path} platform={platform}")
        return executions
    for suite in suites:
        suite_name = suite.attrib.get("name") or path.stem
        suite_testcases = [child for child in list(suite) if local_name(child) == "testcase"]
        if not suite_testcases:
            log_warn(f"empty testsuite file={path} platform={platform} suite={suite_name}")
        for testcase in suite_testcases:
            logical_id, classname, name = logical_test_identity(testcase, source_id)
            status = testcase_status(testcase)
            reason, output = testcase_reason_and_output(testcase, status)
            executions.append(
                TestcaseExecution(
                    platform=platform,
                    source_file=path,
                    source_id=source_id,
                    suite_name=suite_name,
                    classname=classname,
                    name=name,
                    logical_id=logical_id,
                    status=status,
                    duration_seconds=duration_seconds(testcase),
                    reason=reason,
                    output=output,
                )
            )
    status_counts = Counter(execution.status for execution in executions)
    suite_names = sorted({execution.suite_name for execution in executions})
    log_info(
        f"parsed file={path} platform={platform} suites={len(suite_names)} "
        f"testcases={len(executions)} status_counts={format_counts(status_counts)}"
    )
    for execution in executions:
        if execution.status in {"SKIPPED", "FAILED", "ERRORED"}:
            log_info(
                f"{execution.status} test={execution.logical_id} platform={execution.platform} "
                f"suite={execution.suite_name} reason={execution.reason or '<none>'} file={execution.source_file}"
            )
    return executions


def build_report(
    title: str,
    platform_specs: List[Tuple[str, Union[Path, str]]],
    build_url: Optional[str] = None,
    commit_url: Optional[str] = None,
) -> Report:
    log_info(f"Start JUnit report model build title={title!r} platforms={len(platform_specs)}")
    suites: "OrderedDict[str, TestSuite]" = OrderedDict()
    total_files = 0
    total_raw_executions = 0
    all_files_to_process = []
    duplicates_seen = 0
    duplicates_replaced = 0

    for platform, raw_path in platform_specs:
        input_path = Path(raw_path)
        log_info(f"Inspect platform={platform} path={input_path}")
        platform_xml_files = discover_xml_files(input_path)
        total_files += len(platform_xml_files)
        log_info(f"platform={platform} discovered {len(platform_xml_files)} XML file(s)")
        for xml_file in platform_xml_files:
            rel_path = (
                xml_file.relative_to(
                    input_path.parent if input_path.is_file() else input_path
                ).as_posix()
                if input_path.is_dir()
                else xml_file.name
            )
            # Strip UUIDs and the platform name from the source_id components.
            # We keep UUIDs in the physical path to avoid file collisions when
            # multiple parallel Buildkite jobs upload the same filename, but
            # we strip them from the logical identity so the report correctly
            # aggregates results from all parallel jobs into a single row.
            parts = rel_path.split("/")
            source_id = (
                "/".join(p for p in parts if not UUID_RE.match(p) and p != platform) or rel_path
            )
            all_files_to_process.append((platform, xml_file, source_id))

    if not all_files_to_process:
        log_warn("No JUnit XML files discovered across all platforms")

    log_info("Omitting filename prefix from all test identities")

    for platform, xml_file, source_id in all_files_to_process:
        file_executions = parse_junit_file(xml_file, platform, source_id)
        total_raw_executions += len(file_executions)
        for execution in file_executions:
            suite = suites.get(execution.suite_name)
            if suite is None:
                suite = TestSuite(name=execution.suite_name)
                suites[execution.suite_name] = suite
                log_info(f"created testsuite suite={execution.suite_name}")
            logical = suite.logical_tests.get(execution.logical_id)
            if logical is None:
                logical = LogicalTest(
                    suite_name=execution.suite_name,
                    logical_id=execution.logical_id,
                    classname=execution.classname,
                    name=execution.name,
                )
                suite.logical_tests[execution.logical_id] = logical
            existing = logical.executions.get(platform)
            if existing is None:
                logical.executions[platform] = execution
            else:
                duplicates_seen += 1
                chosen = worse_execution(existing, execution)
                if chosen is execution:
                    duplicates_replaced += 1
                    log_warn(
                        f"duplicate replaced test={execution.logical_id} platform={platform} "
                        f"suite={execution.suite_name} old_status={existing.status} "
                        f"new_status={execution.status} old_file={existing.source_file} new_file={execution.source_file}"
                    )
                else:
                    log_warn(
                        f"duplicate kept-existing test={execution.logical_id} platform={platform} "
                        f"suite={execution.suite_name} existing_status={existing.status} "
                        f"duplicate_status={execution.status} existing_file={existing.source_file} duplicate_file={execution.source_file}"
                    )
                logical.executions[platform] = chosen

    report = Report(
        title=title,
        platforms=[platform for platform, _ in platform_specs],
        suites=suites,
        build_url=build_url,
        commit_url=commit_url,
        generated_at=utc_now_iso(),
        total_files=total_files,
        raw_testcases=total_raw_executions,
        duplicates_seen=duplicates_seen,
        duplicates_replaced=duplicates_replaced,
    )
    log_info(
        f"Summary: files={report.total_files} raw_testcases={report.raw_testcases} suites={len(report.suites)} "
        f"logical_tests={report.logical_test_count} platform_executions={report.platform_execution_count} "
        f"duplicates_seen={report.duplicates_seen} duplicates_replaced={report.duplicates_replaced} "
        f"status_counts={format_counts(report.status_counts)} root_status={report.root_status}"
    )
    if report.root_status in {"FAILED", "ERRORED"}:
        log_warn(
            f"Report model completed with root_status={report.root_status}; see FAILED/ERRORED lines above for details"
        )
    return report
