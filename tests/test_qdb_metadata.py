import json
import xml.etree.ElementTree as ET

import pytest
from junit_report_model import (
    ArtifactLink,
    build_report,
    qdb_metadata,
    source_artifacts_for_junit,
)
from report_data import report_to_report_ui_data

LOG_PATH = "test_log/qdb_test_log_pid_90560_1724412755000000000.json"


def suite_xml(record):
    suite = ET.Element("testsuite", name="qdb_unit_tests", tests="1")
    ET.SubElement(suite, "testcase", classname="acl", name="works", time="0.1")
    ET.SubElement(suite, "system-out").text = (
        "Test program PID [90560] running as 'ci' on 'linux'\n"
        "INFO:\n- message: QDB_TEST_METADATA " + json.dumps(record) + "\n\n"
    )
    return suite


def artifact(path, key=None):
    return ArtifactLink("QDB test logs", path, key or path, None, 123)


def test_structured_metadata_matches_exact_log_within_source_job(tmp_path):
    suite = suite_xml({"version": 1, "pid": 90560, "log_path": LOG_PATH})
    path = tmp_path / "qdb_auth_test.xml"
    ET.ElementTree(suite).write(path, encoding="utf-8")
    matching = artifact(LOG_PATH)
    reused_pid = artifact(LOG_PATH.replace("1724412755000000000", "999"))
    other_job = artifact(LOG_PATH, "other-job/" + LOG_PATH)
    report = build_report(
        "metadata",
        [("linux", path)],
        source_job_id="job-1",
        source_artifacts_by_job_id={
            "job-1": [reused_pid, matching],
            "job-2": [other_job],
        },
    )
    execution = (
        report.suites["qdb_unit_tests"]
        .test_files["qdb_auth_test"]
        .logical_tests["acl::works"]
        .executions["linux"]
    )
    assert execution.qdb_process_id == "90560"
    assert execution.qdb_log_path == LOG_PATH
    assert execution.source_artifacts == [matching]
    assert report.raw_testcases == 1
    ui = report_to_report_ui_data(report)[0]
    assert ui["sourceTables"]["qdbProcessIds"] == ["90560"]
    assert len(ui["sourceArtifactTable"]) == 1
    assert ui["sourceArtifactTable"][0]["relativePath"] == LOG_PATH


def test_missing_explicit_log_does_not_fall_back_to_reused_pid(capsys):
    reused_pid = artifact(LOG_PATH.replace("1724412755000000000", "999"))
    assert source_artifacts_for_junit("90560", [reused_pid], qdb_log_path=LOG_PATH) == []
    assert "was not uploaded for this job" in capsys.readouterr().err


def test_explicit_log_path_normalizes_separators_and_keeps_query_artifacts():
    matching = artifact(LOG_PATH.replace("/", "\\"))
    query = artifact("server-logs/query.tar.gz")
    unrelated = artifact("server-logs/other.tar.gz")
    assert source_artifacts_for_junit(
        "90560", [matching, query, unrelated], "query", "./" + LOG_PATH
    ) == [query, matching]


def test_pid_only_metadata_and_legacy_metadata_remain_supported():
    assert qdb_metadata(suite_xml({"version": 1, "pid": 90560})) == ("90560", None)
    legacy = ET.fromstring(
        '<testsuite><testcase name="qdb_test_process_id">'
        "<system-out>90560</system-out></testcase></testsuite>"
    )
    assert qdb_metadata(legacy) == ("90560", None)
    matching = artifact(LOG_PATH)
    assert source_artifacts_for_junit("90560", [matching]) == [matching]


def test_structured_metadata_takes_precedence_over_legacy_testcase():
    suite = suite_xml({"version": 1, "pid": 90560, "log_path": LOG_PATH})
    case = ET.SubElement(suite, "testcase", name="qdb_test_process_id")
    ET.SubElement(case, "system-out").text = "123"
    assert qdb_metadata(suite) == ("90560", LOG_PATH)


def test_testcase_output_cannot_supply_executable_metadata():
    suite = suite_xml({"version": 1, "pid": 90560, "log_path": LOG_PATH})
    output = suite.find("system-out")
    suite.remove(output)
    suite.find("testcase").append(output)
    assert qdb_metadata(suite) == (None, None)


def test_namespaced_metadata_in_testsuites_wrapper():
    suite = suite_xml({"version": 1, "pid": 90560, "log_path": LOG_PATH})
    for element in suite.iter():
        element.tag = "{urn:junit}" + element.tag
    root = ET.Element("{urn:junit}testsuites")
    root.append(suite)
    assert qdb_metadata(root) == ("90560", LOG_PATH)


@pytest.mark.parametrize(
    "record",
    [
        {"version": 2, "pid": 90560},
        {"version": True, "pid": 90560},
        {"version": 1, "pid": True},
        {"version": 1, "pid": -1},
        {"version": 1, "pid": "90560"},
        {"version": 1, "pid": 90560, "log_path": None},
        {"version": 1, "pid": 90560, "log_path": ""},
        [],
    ],
)
def test_invalid_metadata_is_ignored_with_warning(record, capsys):
    assert qdb_metadata(suite_xml(record)) == (None, None)
    assert "ignoring" in capsys.readouterr().err


def test_malformed_json_is_ignored_with_warning(capsys):
    suite = suite_xml({})
    suite.find("system-out").text = "QDB_TEST_METADATA {invalid}"
    assert qdb_metadata(suite) == (None, None)
    assert "malformed" in capsys.readouterr().err


def test_conflicting_records_are_not_assigned_to_every_testcase(capsys):
    root = ET.Element("testsuites")
    root.append(suite_xml({"version": 1, "pid": 90560, "log_path": LOG_PATH}))
    root.append(suite_xml({"version": 1, "pid": 123}))
    assert qdb_metadata(root) == (None, None)
    assert "conflicting" in capsys.readouterr().err
