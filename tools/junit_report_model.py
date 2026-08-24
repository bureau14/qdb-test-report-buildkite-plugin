#!/usr/bin/env python3
"""Parse JUnit XML files into a neutral report model."""

from __future__ import annotations

import argparse
import glob
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

STATUS_ORDER = ["SUCCESSFUL", "SKIPPED", "FAILED", "ERRORED"]
STATUS_SEVERITY = {"SUCCESSFUL": 0, "SKIPPED": 1, "FAILED": 2, "ERRORED": 3}

# Pattern to match Buildkite Job IDs (UUIDs). We strip these from test identities
# to support Buildkite parallelism: multiple jobs for the same variant can each
# upload their own JUnit XML without being treated as distinct tests in the report.
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
QDB_PROCESS_ID_TESTCASE = "qdb_test_process_id"
QDB_TEST_LOG_NAME_RE = re.compile(r"^qdb_test_log_pid_(\d+)_.+\.json$")


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
class ArtifactLink:
    name: str
    relative_path: str
    key: str
    url: str | None
    size_bytes: int


@dataclass
class TestcaseExecution:
    platform: str
    source_file: Path
    source_id: str
    test_file: str
    source_job_id: str | None
    source_job_url: str | None
    source_xml_url: str | None
    suite_name: str
    classname: str
    name: str
    logical_id: str
    status: str
    duration_seconds: float
    reason: str | None = None
    output: str | None = None
    source_artifacts: list[ArtifactLink] = field(default_factory=list)
    qdb_process_id: str | None = None


@dataclass
class LogicalTest:
    suite_name: str
    test_file: str
    logical_id: str
    classname: str
    name: str
    executions: OrderedDict[str, TestcaseExecution] = field(default_factory=OrderedDict)


@dataclass
class TestFile:
    name: str
    logical_tests: OrderedDict[str, LogicalTest] = field(default_factory=OrderedDict)


@dataclass
class TestSuite:
    name: str
    test_files: OrderedDict[str, TestFile] = field(default_factory=OrderedDict)


@dataclass
class Report:
    title: str
    platforms: list[str]
    suites: OrderedDict[str, TestSuite]
    build_url: str | None = None
    commit_url: str | None = None
    generated_at: str = ""
    total_files: int = 0
    raw_testcases: int = 0
    duplicates_seen: int = 0
    duplicates_replaced: int = 0
    malformed_junit_xml: list[dict[str, str]] = field(default_factory=list)
    artifacts: list[ArtifactLink] = field(default_factory=list)

    @property
    def resolved_platforms(self) -> list[str]:
        """Returns the list of platforms that actually had at least one test execution."""
        seen = set()
        for suite in self.suites.values():
            for test_file in suite.test_files.values():
                for logical in test_file.logical_tests.values():
                    for platform in logical.executions:
                        seen.add(platform)
        return [p for p in self.platforms if p in seen]

    @property
    def logical_test_count(self) -> int:
        return sum(
            len(test_file.logical_tests)
            for suite in self.suites.values()
            for test_file in suite.test_files.values()
        )

    @property
    def platform_execution_count(self) -> int:
        return sum(
            len(logical.executions)
            for suite in self.suites.values()
            for test_file in suite.test_files.values()
            for logical in test_file.logical_tests.values()
        )

    @property
    def duration_seconds(self) -> float:
        return sum(
            execution.duration_seconds
            for suite in self.suites.values()
            for test_file in suite.test_files.values()
            for logical in test_file.logical_tests.values()
            for execution in logical.executions.values()
        )

    @property
    def status_counts(self) -> Counter[str]:
        return Counter(
            execution.status
            for suite in self.suites.values()
            for test_file in suite.test_files.values()
            for logical in test_file.logical_tests.values()
            for execution in logical.executions.values()
        )

    @property
    def logical_status_counts(self) -> Counter[str]:
        return Counter(
            logical_status(logical)
            for suite in self.suites.values()
            for test_file in suite.test_files.values()
            for logical in test_file.logical_tests.values()
        )

    @property
    def root_status(self) -> str:
        return aggregate_status(list(self.status_counts.elements()))


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def has_glob_magic(path: Path | str) -> bool:
    return any(char in str(path) for char in "*?[]")


def discover_xml_files(path: Path | str) -> list[Path]:
    """Return XML files for a file, directory, or glob in discovery order."""
    input_path = Path(path)
    if has_glob_magic(input_path):
        seen = set()
        files = []
        for match in glob.glob(str(input_path), recursive=True):
            candidate = Path(match).resolve()
            if candidate.is_file() and candidate.suffix == ".xml" and candidate not in seen:
                seen.add(candidate)
                files.append(candidate)
        return files
    if input_path.is_file():
        return [input_path]
    if input_path.is_dir():
        return [p for p in input_path.rglob("*.xml") if p.is_file()]
    log_warn(f"JUnit path does not exist: {input_path}")
    return []


def parse_platform_arg(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("platform must use name=path format")
    name, raw_path = value.split("=", 1)
    if not name.strip():
        raise argparse.ArgumentTypeError("platform name cannot be empty")
    if not raw_path.strip():
        raise argparse.ArgumentTypeError("platform path cannot be empty")
    return name.strip(), Path(raw_path)


def logical_test_identity(testcase: ET.Element, source_id: str) -> tuple[str, str, str]:
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


def specific_reason_from_text(text: str | None) -> str | None:
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


def testcase_reason_and_output(testcase: ET.Element, status: str) -> tuple[str | None, str | None]:
    if status == "ERRORED":
        node = testcase.find("error")
    elif status == "FAILED":
        node = testcase.find("failure")
    elif status == "SKIPPED":
        node = testcase.find("skipped")
    else:
        node = None

    reason = None
    output_parts: list[str] = []
    if node is not None:
        raw_message = node.attrib.get("message")
        node_text = node.text.strip() if node.text and node.text.strip() else None
        if node_text:
            output_parts.append(node_text)
        if (
            status == "SKIPPED"
            and raw_message
            or raw_message
            and raw_message.lower() not in {"failure", "error"}
        ):
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


def aggregate_status(statuses: list[str]) -> str:
    if any(status == "ERRORED" for status in statuses):
        return "ERRORED"
    if any(status == "FAILED" for status in statuses):
        return "FAILED"
    # Skips are treated as success for the purpose of the overall report status.
    return "SUCCESSFUL"


def buildkite_job_url(build_url: str | None, job_id: str | None) -> str | None:
    if not build_url or not job_id:
        return None
    return f"{build_url.split('#', 1)[0]}#{job_id}"


def test_file_name(source_id: str) -> str:
    source_path = Path(source_id)
    return source_path.stem or source_path.name or "<unknown>"


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


def testcase_system_out(testcase: ET.Element) -> str | None:
    for child in testcase:
        if local_name(child) == "system-out" and child.text:
            return child.text.strip() or None
    return None


def qdb_process_id(root: ET.Element) -> str | None:
    values = {
        value
        for testcase in root.iter()
        if local_name(testcase) == "testcase"
        and testcase.attrib.get("name") == QDB_PROCESS_ID_TESTCASE
        and (value := testcase_system_out(testcase)) is not None
        and value.isdecimal()
    }
    if len(values) == 1:
        return values.pop()
    if values:
        log_warn(f"conflicting {QDB_PROCESS_ID_TESTCASE} values: {sorted(values)}")
    return None


def is_qdb_test_log(artifact: ArtifactLink) -> bool:
    return QDB_TEST_LOG_NAME_RE.fullmatch(Path(artifact.relative_path).name) is not None


def source_artifacts_for_junit(
    qdb_pid: str | None, artifacts: list[ArtifactLink]
) -> list[ArtifactLink]:
    non_qdb_logs = [artifact for artifact in artifacts if not is_qdb_test_log(artifact)]
    if not qdb_pid:
        return non_qdb_logs
    return non_qdb_logs + [
        artifact
        for artifact in artifacts
        if (match := QDB_TEST_LOG_NAME_RE.fullmatch(Path(artifact.relative_path).name))
        and match.group(1) == qdb_pid
    ]


def iter_junit_suites(root: ET.Element) -> list[ET.Element]:
    if local_name(root) == "testsuite":
        return [root]
    return [element for element in root.iter() if local_name(element) == "testsuite"]


def parse_junit_file(
    path: Path,
    platform: str,
    source_id: str | None = None,
    source_job_id: str | None = None,
    source_job_url: str | None = None,
    source_xml_url: str | None = None,
    source_artifacts: list[ArtifactLink] | None = None,
    malformed_junit_xml: list[dict[str, str]] | None = None,
) -> list[TestcaseExecution]:
    if source_id is None:
        source_id = path.name
    if path.stat().st_size == 0:
        log_warn(f"skipping empty JUnit XML file file={path} platform={platform}")
        return []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        log_warn(f"skipping malformed JUnit XML file file={path} platform={platform} error={error}")
        if malformed_junit_xml is not None:
            malformed_junit_xml.append(
                {"file": str(path), "platform": platform, "error": str(error)}
            )
        return []
    executions: list[TestcaseExecution] = []
    source_qdb_process_id = qdb_process_id(root)
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
                    test_file=test_file_name(source_id),
                    source_job_id=source_job_id,
                    source_job_url=source_job_url,
                    source_xml_url=source_xml_url,
                    suite_name=suite_name,
                    classname=classname,
                    name=name,
                    logical_id=logical_id,
                    status=status,
                    duration_seconds=duration_seconds(testcase),
                    reason=reason,
                    output=output,
                    source_artifacts=source_artifacts or [],
                    qdb_process_id=source_qdb_process_id,
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
    platform_specs: list[tuple[str, Path | str]],
    build_url: str | None = None,
    commit_url: str | None = None,
    source_job_id: str | None = None,
    source_artifacts_by_job_id: dict[str, list[ArtifactLink]] | None = None,
    artifacts: list[ArtifactLink] | None = None,
    xml_source_links: dict[Path, str | None] | None = None,
) -> Report:
    log_info(f"Start JUnit report model build title={title!r} platforms={len(platform_specs)}")
    suites: OrderedDict[str, TestSuite] = OrderedDict()
    total_files = 0
    total_raw_executions = 0
    all_files_to_process = []
    duplicates_seen = 0
    duplicates_replaced = 0
    malformed_junit_xml: list[dict[str, str]] = []

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
            path_source_job_id = next((p for p in parts if UUID_RE.match(p)), None)
            if (
                path_source_job_id is None
                and source_artifacts_by_job_id is not None
                and parts
                and parts[0] in source_artifacts_by_job_id
            ):
                path_source_job_id = parts[0]
            effective_source_job_id = path_source_job_id or source_job_id
            source_job_url = buildkite_job_url(build_url, effective_source_job_id)
            source_xml_url = (xml_source_links or {}).get(xml_file.resolve())
            source_id = (
                "/".join(p for p in parts if p != path_source_job_id and p != platform) or rel_path
            )
            all_files_to_process.append(
                (
                    platform,
                    xml_file,
                    source_id,
                    effective_source_job_id,
                    source_job_url,
                    source_xml_url,
                )
            )

    if not all_files_to_process:
        log_warn("No JUnit XML files discovered across all platforms")

    log_info("Omitting filename prefix from all test identities")

    for (
        platform,
        xml_file,
        source_id,
        effective_source_job_id,
        source_job_url,
        source_xml_url,
    ) in all_files_to_process:
        file_executions = parse_junit_file(
            xml_file,
            platform,
            source_id,
            source_job_id=effective_source_job_id,
            source_job_url=source_job_url,
            source_xml_url=source_xml_url,
            malformed_junit_xml=malformed_junit_xml,
        )
        qdb_pid = next(
            (execution.qdb_process_id for execution in file_executions if execution.qdb_process_id),
            None,
        )
        matching_artifacts = source_artifacts_for_junit(
            qdb_pid,
            (source_artifacts_by_job_id or {}).get(effective_source_job_id or "", []),
        )
        for execution in file_executions:
            execution.source_artifacts = matching_artifacts
        total_raw_executions += len(file_executions)
        for execution in file_executions:
            suite = suites.get(execution.suite_name)
            if suite is None:
                suite = TestSuite(name=execution.suite_name)
                suites[execution.suite_name] = suite
                log_info(f"created testsuite suite={execution.suite_name}")
            test_file = suite.test_files.get(execution.test_file)
            if test_file is None:
                test_file = TestFile(name=execution.test_file)
                suite.test_files[execution.test_file] = test_file
                log_info(
                    f"created testfile suite={execution.suite_name} test_file={execution.test_file}"
                )
            logical = test_file.logical_tests.get(execution.logical_id)
            if logical is None:
                logical = LogicalTest(
                    suite_name=execution.suite_name,
                    test_file=execution.test_file,
                    logical_id=execution.logical_id,
                    classname=execution.classname,
                    name=execution.name,
                )
                test_file.logical_tests[execution.logical_id] = logical
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
                        f"suite={execution.suite_name} test_file={execution.test_file} old_status={existing.status} "
                        f"new_status={execution.status} old_file={existing.source_file} new_file={execution.source_file}"
                    )
                else:
                    log_warn(
                        f"duplicate kept-existing test={execution.logical_id} platform={platform} "
                        f"suite={execution.suite_name} test_file={execution.test_file} existing_status={existing.status} "
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
        malformed_junit_xml=malformed_junit_xml,
        artifacts=artifacts or [],
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
