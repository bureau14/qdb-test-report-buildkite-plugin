"""Parse JUnit XML files into a neutral report model."""

from __future__ import annotations

import argparse
import glob
import logging
import os
import re
import xml.etree.ElementTree as ET
from collections import Counter, OrderedDict, deque
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import islice
from multiprocessing import get_context
from pathlib import Path

from report_logging import configure_logging, logger, traced

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
MAX_EMBEDDED_TEST_OUTPUT_BYTES = 256 * 1024


def log_info(message: str) -> None:
    logger.info(message)


def log_warn(message: str) -> None:
    logger.warning(message)


def format_counts(counter: Counter[str]) -> str:
    parts = [f"{status}={counter[status]}" for status in STATUS_ORDER if counter[status]]
    for key in sorted(counter):
        if key not in STATUS_ORDER and counter[key]:
            parts.append(f"{key}={counter[key]}")
    return ", ".join(parts) if parts else "none"


def cap_embedded_test_output(output: str) -> str:
    encoded_output = output.encode("utf-8")
    if len(encoded_output) <= MAX_EMBEDDED_TEST_OUTPUT_BYTES:
        return output

    message = (
        f"[Output truncated from {len(encoded_output)} bytes. "
        "Inspect the full JUnit XML for complete output.]\n\n"
    )
    message_bytes = message.encode("utf-8")
    preview_bytes = MAX_EMBEDDED_TEST_OUTPUT_BYTES - len(message_bytes)

    preview = encoded_output[-preview_bytes:].decode("utf-8", errors="ignore")
    return f"{message}{preview}"


@dataclass
class ArtifactLink:
    name: str
    relative_path: str
    key: str
    url: str | None
    size_bytes: int
    execution_id: str | None = None


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
    execution_id: str | None = None
    report_kind: str = "test"


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
    junit_archive_errors: list[dict[str, str]] = field(default_factory=list)
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
    def report_durations_seconds(self) -> dict[str, float]:
        durations: dict[str, float] = {}
        for suite in self.suites.values():
            for test_file in suite.test_files.values():
                for logical in test_file.logical_tests.values():
                    for execution in logical.executions.values():
                        if execution.report_kind != "ctest":
                            durations[test_file.name] = (
                                durations.get(test_file.name, 0.0) + execution.duration_seconds
                            )
        return durations

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
        if self.junit_archive_errors:
            return "ERRORED"
        return aggregate_status(list(self.status_counts.elements()))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def has_glob_magic(path: Path | str) -> bool:
    return any(char in str(path) for char in "*?[]")


@traced("model.xml.discover")
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
    if find_child(testcase, "error") is not None:
        return "ERRORED"
    if find_child(testcase, "failure") is not None:
        return "FAILED"
    if find_child(testcase, "skipped") is not None:
        return "SKIPPED"
    return "SUCCESSFUL"


def specific_reason_from_text(text: str | None) -> str | None:
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if line.startswith("- message:"):
            return line[len("- message:") :].strip()
    for line in lines:
        if line not in {"ASSERTION FAILURE:", "Failures detected in:"}:
            return line
    return lines[0] if lines else None


def testcase_reason_and_output(testcase: ET.Element, status: str) -> tuple[str | None, str | None]:
    if status == "ERRORED":
        node = find_child(testcase, "error")
    elif status == "FAILED":
        node = find_child(testcase, "failure")
    elif status == "SKIPPED":
        node = find_child(testcase, "skipped")
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

    # Detailed stdout and stderr can dominate the static report, so retain them only where
    # they diagnose a failed execution. Full output remains available in the JUnit XML.
    if status in {"FAILED", "ERRORED"}:
        for output_name in ("system-out", "system-err"):
            output_node = find_child(testcase, output_name)
            output_text = (
                output_node.text.strip() if output_node is not None and output_node.text else None
            )
            if output_text:
                output_parts.append(output_text)

    output = "\n\n".join(output_parts) if output_parts else None
    return reason, cap_embedded_test_output(output) if output else None


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


def find_child(element: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in element if local_name(child) == name), None)


def testcase_system_out(testcase: ET.Element) -> str | None:
    for child in testcase:
        if local_name(child) == "system-out" and child.text:
            return child.text.strip() or None
    return None


def should_omit_boost_disabled_testcase(testcase: ET.Element) -> bool:
    # Boost emits the same skipped element for selection exclusions and runtime
    # skips. Only its diagnostic chain identifies the ordinary disabled state.
    if testcase_status(testcase) != "SKIPPED":
        return False
    output = testcase_system_out(testcase)
    return bool(
        output
        and output.startswith("Test case disabled because of the following chain of decision:\n")
        and output.endswith("- reason: 'disabled'")
    )


def qdb_process_id(root: ET.Element) -> str | None:
    values = set()
    for testcase in root.iter():
        if (
            local_name(testcase) != "testcase"
            or testcase.attrib.get("name") != QDB_PROCESS_ID_TESTCASE
        ):
            continue
        output = testcase_system_out(testcase)
        if output is not None:
            value = output.splitlines()[0].strip()
            if value.isdecimal():
                values.add(value)

    if len(values) == 1:
        return values.pop()
    if values:
        log_warn(f"conflicting {QDB_PROCESS_ID_TESTCASE} values: {sorted(values)}")
    return None


def is_qdb_test_log(artifact: ArtifactLink) -> bool:
    return QDB_TEST_LOG_NAME_RE.fullmatch(Path(artifact.relative_path).name) is not None


def artifact_matches_junit_filename(artifact: ArtifactLink, junit_filename_stem: str) -> bool:
    artifact_name = Path(artifact.relative_path).name
    # A substring match leaks logs from similarly prefixed suites, such as a
    # transient_single report receiving transient_single_parallelism logs. Match
    # the whole XML stem and allow only ordinary filename extensions after it.
    return (
        re.fullmatch(
            rf"{re.escape(junit_filename_stem)}(?:\.[^.]+)*", artifact_name, flags=re.IGNORECASE
        )
        is not None
    )


def source_artifacts_for_junit(
    qdb_pid: str | None,
    artifacts: list[ArtifactLink],
    junit_filename_stem: str | None = None,
    execution_id: str | None = None,
) -> list[ArtifactLink]:
    if execution_id is not None:
        return [artifact for artifact in artifacts if artifact.execution_id == execution_id]
    artifacts = [artifact for artifact in artifacts if artifact.execution_id is None]
    non_qdb_logs = [artifact for artifact in artifacts if not is_qdb_test_log(artifact)]
    matching_pid_artifacts = []
    for artifact in artifacts:
        match = QDB_TEST_LOG_NAME_RE.fullmatch(Path(artifact.relative_path).name)
        if match and qdb_pid and match.group(1) == qdb_pid:
            matching_pid_artifacts.append(artifact)
    if junit_filename_stem:
        matching_junit_artifacts = [
            artifact
            for artifact in artifacts
            if artifact_matches_junit_filename(artifact, junit_filename_stem)
        ]
        if matching_junit_artifacts:
            return matching_junit_artifacts + [
                artifact
                for artifact in matching_pid_artifacts
                if artifact not in matching_junit_artifacts
            ]
    return non_qdb_logs + matching_pid_artifacts


def iter_junit_suites(root: ET.Element) -> list[ET.Element]:
    if local_name(root) == "testsuite":
        return [root]
    return [element for element in root.iter() if local_name(element) == "testsuite"]


@traced("model.xml.parse", level=logging.DEBUG)
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
        logger.error(
            f"skipping malformed JUnit XML file file={path} platform={platform} error={error}"
        )
        if malformed_junit_xml is not None:
            malformed = {"file": str(path), "platform": platform, "error": str(error)}
            if source_xml_url:
                malformed["url"] = source_xml_url
            malformed_junit_xml.append(malformed)
        return []
    executions: list[TestcaseExecution] = []
    source_qdb_process_id = qdb_process_id(root)
    suites = iter_junit_suites(root)
    if not suites:
        log_warn(f"no testsuite elements found file={path} platform={platform}")
        return executions
    source_test_file = test_file_name(source_id)
    for suite in suites:
        suite_name = suite.attrib.get("name") or path.stem
        execution_id = next(
            (
                item.attrib.get("value")
                for properties in suite
                if local_name(properties) == "properties"
                for item in properties
                if local_name(item) == "property" and item.attrib.get("name") == "qdb.execution_id"
            ),
            None,
        )
        suite_testcases = [child for child in list(suite) if local_name(child) == "testcase"]
        if not suite_testcases:
            log_warn(f"empty testsuite file={path} platform={platform} suite={suite_name}")
        for testcase in suite_testcases:
            if should_omit_boost_disabled_testcase(testcase):
                continue
            logical_id, classname, name = logical_test_identity(testcase, source_id)
            # CTest has no generator marker, but emits these suite attributes,
            # execution statuses, and identical class/test names.
            is_ctest = (
                {"disabled", "hostname", "timestamp"} <= suite.attrib.keys()
                and testcase.attrib.get("status") in {"run", "fail", "notrun", "disabled"}
                and classname == name
            )
            status = testcase_status(testcase)
            reason, output = testcase_reason_and_output(testcase, status)
            executions.append(
                TestcaseExecution(
                    platform=platform,
                    source_file=path,
                    source_id=source_id,
                    test_file=source_test_file,
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
                    execution_id=execution_id,
                    report_kind="ctest" if is_ctest else "test",
                )
            )
    if logger.isEnabledFor(logging.DEBUG):
        status_counts = Counter(execution.status for execution in executions)
        suite_names = sorted({execution.suite_name for execution in executions})
        logger.debug(
            f"parsed file={path} platform={platform} suites={len(suite_names)} "
            f"testcases={len(executions)} status_counts={format_counts(status_counts)}"
        )
        for execution in executions:
            if execution.status in {"SKIPPED", "FAILED", "ERRORED"}:
                logger.debug(
                    f"{execution.status} test={execution.logical_id} platform={execution.platform} "
                    f"suite={execution.suite_name} reason={execution.reason or '<none>'} file={execution.source_file}"
                )
    return executions


def _parse_junit_batch(batch):
    """Parse files without mutating the parent report or its diagnostics."""
    results = []
    for platform, path, source_id, job_id, job_url, xml_url in batch:
        diagnostics = []
        executions = parse_junit_file(
            path,
            platform,
            source_id,
            source_job_id=job_id,
            source_job_url=job_url,
            source_xml_url=xml_url,
            malformed_junit_xml=diagnostics,
        )
        results.append((platform, job_id, executions, diagnostics))
    return results


def _iter_junit_batches(files):
    """Group small XML files while leaving oversized files in their own batch."""
    batch = []
    batch_bytes = 0
    for item in files:
        size = item[1].stat().st_size
        if batch and (len(batch) >= 16 or batch_bytes + size > 16 * 1024 * 1024):
            yield batch
            batch = []
            batch_bytes = 0
        batch.append(item)
        batch_bytes += size
    if batch:
        yield batch


def _iter_parsed_junit_files(files, workers: int):
    """Yield results in discovery order with a bounded number of pending batches."""
    if workers < 1:
        raise ValueError("parse_workers must be at least 1")
    if os.name == "nt":
        workers = min(workers, 61)
    if workers == 1 or len(files) < 2:
        for item in files:
            yield _parse_junit_batch([item])[0]
        return
    batches = iter(_iter_junit_batches(files))
    initial_batches = list(islice(batches, 2 * workers))
    if len(initial_batches) == 1:
        yield from _parse_junit_batch(initial_batches[0])
        return
    level = logger.getEffectiveLevel()
    worker_log_level = "fatal" if level == logging.CRITICAL else logging.getLevelName(level).lower()
    with ProcessPoolExecutor(
        max_workers=min(workers, len(initial_batches)),
        mp_context=get_context("spawn"),
        initializer=configure_logging,
        initargs=(worker_log_level,),
    ) as pool:
        pending = deque()
        for batch in initial_batches:
            pending.append(pool.submit(_parse_junit_batch, batch))
        while pending:
            # Equal-severity duplicates must keep the same first execution as serial parsing.
            results = pending.popleft().result()
            batch = next(batches, None)
            if batch is not None:
                pending.append(pool.submit(_parse_junit_batch, batch))
            yield from results


@traced("model.build")
def build_report(
    title: str,
    platform_specs: list[tuple[str, Path | str]],
    build_url: str | None = None,
    commit_url: str | None = None,
    source_job_id: str | None = None,
    source_artifacts_by_job_id: dict[str, list[ArtifactLink]] | None = None,
    artifacts: list[ArtifactLink] | None = None,
    xml_source_links: dict[Path, str | None] | None = None,
    parse_workers: int = 1,
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
                if not has_glob_magic(input_path) and input_path.is_dir()
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

    log_info(f"Parsing JUnit XML with workers={parse_workers}")
    for platform, effective_source_job_id, file_executions, diagnostics in _iter_parsed_junit_files(
        all_files_to_process, parse_workers
    ):
        malformed_junit_xml.extend(diagnostics)
        if file_executions:
            first_execution = file_executions[0]
            # The source XML's process ID and filename apply to every testcase,
            # so match its artifacts once rather than rescanning them per testcase.
            job_artifacts = (source_artifacts_by_job_id or {}).get(
                effective_source_job_id or "", []
            )
            matches_by_execution = {}
            for execution in file_executions:
                if execution.execution_id not in matches_by_execution:
                    arguments = (
                        first_execution.qdb_process_id,
                        job_artifacts,
                        first_execution.test_file,
                    )
                    matches_by_execution[execution.execution_id] = (
                        source_artifacts_for_junit(*arguments, execution_id=execution.execution_id)
                        if execution.execution_id is not None
                        else source_artifacts_for_junit(*arguments)
                    )
                execution.source_artifacts = matches_by_execution[execution.execution_id]
        total_raw_executions += len(file_executions)
        for execution in file_executions:
            suite = suites.get(execution.suite_name)
            if suite is None:
                suite = TestSuite(name=execution.suite_name)
                suites[execution.suite_name] = suite
                logger.debug("created testsuite suite=%s", execution.suite_name)
            test_file = suite.test_files.get(execution.test_file)
            if test_file is None:
                test_file = TestFile(name=execution.test_file)
                suite.test_files[execution.test_file] = test_file
                logger.debug(
                    "created testfile suite=%s test_file=%s",
                    execution.suite_name,
                    execution.test_file,
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
                    logger.debug(
                        "duplicate replaced test=%s platform=%s suite=%s test_file=%s "
                        "old_status=%s new_status=%s old_file=%s new_file=%s",
                        execution.logical_id,
                        platform,
                        execution.suite_name,
                        execution.test_file,
                        existing.status,
                        execution.status,
                        existing.source_file,
                        execution.source_file,
                    )
                else:
                    logger.debug(
                        "duplicate kept-existing test=%s platform=%s suite=%s test_file=%s "
                        "existing_status=%s duplicate_status=%s existing_file=%s duplicate_file=%s",
                        execution.logical_id,
                        platform,
                        execution.suite_name,
                        execution.test_file,
                        existing.status,
                        execution.status,
                        existing.source_file,
                        execution.source_file,
                    )
                logical.executions[platform] = chosen

    report = Report(
        title=title,
        platforms=list(dict.fromkeys(platform for platform, _ in platform_specs)),
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
    if logger.isEnabledFor(logging.INFO):
        log_info(
            f"Summary: files={report.total_files} raw_testcases={report.raw_testcases} suites={len(report.suites)} "
            f"logical_tests={report.logical_test_count} platform_executions={report.platform_execution_count} "
            f"duplicates_seen={report.duplicates_seen} duplicates_replaced={report.duplicates_replaced} "
            f"status_counts={format_counts(report.status_counts)} root_status={report.root_status}"
        )
    if logger.isEnabledFor(logging.WARNING) and report.root_status in {"FAILED", "ERRORED"}:
        log_warn(
            f"Report model completed with root_status={report.root_status}; see the HTML report for details"
        )
    return report
