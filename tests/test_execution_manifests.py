import json
from pathlib import Path

import pytest
from execution_manifest import load_manifests, manifest_artifacts, validate_manifest
from fastjsonschema import JsonSchemaValueException
from junit_report_model import ArtifactLink, build_report
from report_data import report_to_report_ui_data


def manifest(**changes):
    data = {
        "version": 1,
        "execution_id": "run-1",
        "name": "query",
        "junit": "test-reports/query.xml",
        "status": "completed",
        "exit_code": 0,
        "processes": [{"role": "runner", "pid": 123}],
        "artifacts": [{"role": "runner-log", "path": "logs/runner.json"}],
    }
    return dict(data, **changes)


def executions(report):
    return [
        e
        for suite in report.suites.values()
        for file in suite.test_files.values()
        for test in file.logical_tests.values()
        for e in test.executions.values()
    ]


def source(root, data, job="job-1", platform="linux"):
    return {
        "platform": platform,
        "job_id": job,
        "path": "test-metadata/run.json",
        "manifest": data,
        "junit_local": str(root / data["junit"]),
    }


@pytest.mark.parametrize(
    "path", ["../secret", "/absolute", "C:/secret", "a/../b", "a\\\\b", "./x", "a//b"]
)
def test_unsafe_paths_rejected(path):
    with pytest.raises(JsonSchemaValueException):
        validate_manifest(manifest(junit=path))


def test_schema_example():
    example = Path(__file__).parents[1] / "schemas/examples/query-execution.json"
    validate_manifest(json.loads(example.read_text()))


def test_versions_and_completed_exit_status_are_validated():
    for change in (
        {"version": 2},
        {"version": True},
        {"exit_code": 9},
        {"processes": [{"role": "runner", "pid": 0}]},
    ):
        with pytest.raises(JsonSchemaValueException):
            validate_manifest(manifest(**change))


def test_exact_paths_override_legacy_metadata_and_stay_in_job(tmp_path):
    data = manifest()
    path = tmp_path / data["junit"]
    path.parent.mkdir()
    path.write_text(
        '<testsuite name="suite"><testcase name="works"/><system-out>QDB_TEST_METADATA {"version":1,"pid":999}</system-out></testsuite>'
    )
    expected = ArtifactLink("log", "logs/runner.json", "job1-log", None, 1)
    wrong = ArtifactLink("log", "query.tar.gz", "wrong", None, 1)
    report = build_report(
        "test",
        [("linux", path)],
        source_job_id="job-1",
        source_artifacts_by_job_id={"job-1": [wrong, expected], "job-2": [wrong]},
        manifest_sources=[source(tmp_path, data)],
    )
    execution = executions(report)[0]
    assert execution.source_artifacts == [expected]
    assert execution.qdb_process_id == "123"
    assert execution.execution_metadata["execution_id"] == "run-1"
    assert "Execution ID" in json.dumps(report_to_report_ui_data(report))


@pytest.mark.parametrize(
    "status,exit_code", [("running", None), ("aborted", 130), ("failed", 7), ("completed", 0)]
)
def test_no_junit_still_has_execution_error_and_log_links(tmp_path, status, exit_code):
    data = manifest(status=status)
    if exit_code is None:
        data.pop("exit_code")
    else:
        data["exit_code"] = exit_code
    link = ArtifactLink("log", "logs/runner.json", "log", None, 1)
    report = build_report(
        "test",
        [("linux", tmp_path)],
        source_job_id="job-1",
        source_artifacts_by_job_id={"job-1": [link]},
        manifest_sources=[source(tmp_path, data)],
    )
    execution = executions(report)[0]
    assert execution.status == "ERRORED"
    assert execution.source_artifacts == [link]
    assert report.root_status == "ERRORED"


def test_failed_process_with_passing_junit_is_not_green(tmp_path):
    data = manifest(status="failed", exit_code=7)
    path = tmp_path / data["junit"]
    path.parent.mkdir()
    path.write_text('<testsuite name="suite"><testcase name="works"/></testsuite>')
    report = build_report(
        "test",
        [("linux", tmp_path)],
        source_job_id="job-1",
        manifest_sources=[source(tmp_path, data)],
    )
    assert sorted(e.status for e in executions(report)) == ["ERRORED", "SUCCESSFUL"]


def test_missing_explicit_artifact_does_not_fall_back():
    wrong = ArtifactLink("log", "query.tar.gz", "wrong", None, 1)
    links, warnings = manifest_artifacts(manifest(), [wrong], "test-metadata/run.json")
    assert links == []
    assert warnings == ["Missing artifact: logs/runner.json"]


def test_conflicting_claims_rejected(tmp_path):
    for name in ("one", "two"):
        (tmp_path / f"{name}.json").write_text(json.dumps(manifest()))
    with pytest.raises(ValueError, match="multiple execution manifests"):
        load_manifests(tmp_path / "*.json", tmp_path)


def test_aggregate_jobs_with_same_relative_paths_are_isolated(tmp_path):
    sources, artifacts = [], {}
    for job in ("job-a", "job-b"):
        root = tmp_path / job
        path = root / "test-reports/query.xml"
        path.parent.mkdir(parents=True)
        path.write_text(f'<testsuite name="suite"><testcase name="{job}"/></testsuite>')
        sources.append(source(root, manifest(), job))
        artifacts[job] = [ArtifactLink("log", "logs/runner.json", job, None, 1)]
    report = build_report(
        "test",
        [("linux", tmp_path)],
        source_artifacts_by_job_id=artifacts,
        manifest_sources=sources,
    )
    for execution in executions(report):
        assert execution.source_artifacts[0].key == execution.source_job_id == execution.name


@pytest.mark.parametrize(
    "changes",
    [
        {"extra": True},
        {"name": ""},
        {"status": "unknown"},
        {"exit_code": True},
        {"processes": [{"role": "runner", "pid": True}]},
        {"processes": [{"role": "runner", "pid": 1, "pid_namespace": "unknown"}]},
        {"processes": [{"role": "runner"}]},
        {"processes": [{"role": "runner", "pid": 1, "extra": True}]},
        {"artifacts": [{"role": "log", "path": "../secret"}]},
        {"artifacts": [{"role": "log", "path": "log.json", "required": "false"}]},
        {"artifacts": [{"role": "log", "path": "log.json", "extra": True}]},
    ],
)
def test_manifest_field_constraints(changes):
    with pytest.raises(JsonSchemaValueException):
        validate_manifest(manifest(**changes))


@pytest.mark.parametrize("status", ["completed", "failed", "aborted"])
def test_terminal_status_requires_exit_code(status):
    data = manifest(status=status)
    del data["exit_code"]
    with pytest.raises(JsonSchemaValueException):
        validate_manifest(data)
