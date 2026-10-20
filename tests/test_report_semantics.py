import pytest
from junit_report_model import ArtifactLink, build_report
from report_data import report_to_report_ui_data


@pytest.mark.parametrize(
    "suite", ["qdb_unit_tests", "qdb_integration_tests", "qdb_regression_tests"]
)
@pytest.mark.parametrize(
    "output", ["", "<system-out>INFO: check !pid.empty() has passed</system-out>"]
)
def test_boost_process_id_metadata_without_numeric_output_is_not_a_test(tmp_path, suite, output):
    (tmp_path / "boost.xml").write_text(
        f'<testsuite name="{suite}"><testcase name="qdb_test_process_id">{output}</testcase>'
        '<testcase name="works" /></testsuite>'
    )
    report = build_report("report", [("linux", tmp_path)])
    assert report.logical_test_count == 1
    assert report.test_status_counts == {"SUCCESSFUL": 1}


def test_failed_process_id_helper_remains_visible(tmp_path):
    (tmp_path / "boost.xml").write_text(
        '<testsuite name="qdb_unit_tests"><testcase name="qdb_test_process_id">'
        '<system-out>1234</system-out><failure message="PID unavailable" /></testcase></testsuite>'
    )
    report = build_report("report", [("linux", tmp_path)])
    assert report.logical_test_count == 1
    assert report.root_status == "FAILED"


@pytest.mark.parametrize("pid", [None, "1234"])
def test_unmatched_legacy_reports_do_not_receive_other_suites_logs(tmp_path, pid):
    from junit_report_model import source_artifacts_for_junit

    unrelated = ArtifactLink("Query logs", "logs/query.tar.gz", "job/logs.zip", None, 12)
    own = ArtifactLink(
        "QDB test logs", "logs/qdb_test_log_pid_1234_123.json", "job/logs.zip", None, 12
    )
    managed = ArtifactLink(
        "Execution logs", "test-results/id/stdout.log", "job/logs.zip", None, 12, "id", "other"
    )
    assert source_artifacts_for_junit(pid, [unrelated, own, managed], "cleanup") == (
        [own] if pid else []
    )


def test_ctest_links_only_its_execution_and_does_not_inflate_case_totals(tmp_path):
    (
        tmp_path / "ctest.xml"
    ).write_text("""<testsuite name="ctest" disabled="0" hostname="agent" timestamp="today">
      <testcase name="runner" classname="runner" status="run" time="10" />
      <testcase name="other" classname="other" status="run" time="20" />
    </testsuite>""")
    (tmp_path / "runner.xml").write_text("""<testsuite name="suite">
      <properties><property name="qdb.execution_id" value="execution" /></properties>
      <testcase name="qdb_test_process_id"><system-out>1234</system-out></testcase>
      <testcase name="works" time="2" />
      <testcase name="skipped"><skipped /></testcase>
    </testsuite>""")
    own = ArtifactLink(
        "Test execution artifacts",
        "test-results/id/stdout.log",
        "job/logs.zip",
        None,
        12,
        "execution",
        "runner",
    )
    unrelated = ArtifactLink(
        "Test execution artifacts",
        "test-results/other/stdout.log",
        "job/logs.zip",
        None,
        20,
        "different",
        "other",
    )
    legacy = ArtifactLink("Query archives", "unrelated.tar.gz", "job/logs.zip", None, 10)
    report = build_report(
        "report",
        [("linux", tmp_path)],
        source_job_id="job",
        source_artifacts_by_job_id={"job": [own, unrelated, legacy]},
    )
    assert report.logical_test_count == report.platform_execution_count == 2
    assert report.ctest_execution_count == 2
    assert report.duration_seconds == 2
    assert report.ctest_duration_seconds == 30
    assert report.test_status_counts == {"SUCCESSFUL": 1, "SKIPPED": 1}
    assert report.suites["ctest"].test_files["ctest"].logical_tests["runner::runner"].executions[
        "linux"
    ].source_artifacts == [own]
    assert report.suites["ctest"].test_files["ctest"].logical_tests["other::other"].executions[
        "linux"
    ].source_artifacts == [unrelated]
    case = report.suites["suite"].test_files["runner"].logical_tests["works"].executions["linux"]
    assert case.source_artifacts == [own]
    assert case.qdb_process_id == "1234"
    ui = report_to_report_ui_data(report)[0]
    assert ui["durationMillis"] == 2000
    assert ui["summary"]["ctestExecutions"] == 2
    assert ui["summary"]["logicalTests"] == 2
    assert not any("qdb_test_process_id" in node["name"] for node in ui["testNodes"])
    skipped = (
        report.suites["suite"].test_files["runner"].logical_tests["skipped"].executions["linux"]
    )
    assert skipped.reason == "No skip reason provided by the test runner."


def test_failing_ctest_check_still_fails_a_report_with_no_case_results(tmp_path):
    (
        tmp_path / "ctest.xml"
    ).write_text("""<testsuite name="ctest" disabled="0" hostname="agent" timestamp="today">
      <testcase name="runner" classname="runner" status="fail" time="10"><failure message="startup failed" /></testcase>
    </testsuite>""")
    report = build_report("report", [("linux", tmp_path)])
    assert report.logical_test_count == 0
    assert report.test_status_counts == {}
    assert report.ctest_status_counts == {"FAILED": 1}
    assert report.root_status == "FAILED"
    ui = report_to_report_ui_data(report)[0]
    assert ui["summary"]["rootStatus"] == "FAILED"
    assert ui["summary"]["ctestStatusCounts"] == {"FAILED": 1}
    assert any(node.get("status") == "FAILED" for node in ui["testNodes"])


def test_a_real_test_with_the_metadata_name_is_not_hidden(tmp_path):
    (tmp_path / "real.xml").write_text(
        '<testsuite><testcase name="qdb_test_process_id"><system-out>regular output</system-out></testcase></testsuite>'
    )
    assert build_report("report", [("linux", tmp_path)]).logical_test_count == 1


def test_nested_c_api_ctest_cases_are_real_results_with_managed_artifacts(tmp_path):
    (
        tmp_path / "c_api.xml"
    ).write_text("""<testsuite name="qdb_c_api_tests" disabled="0" hostname="agent" timestamp="today">
      <properties><property name="qdb.execution_id" value="c-api-execution" /></properties>
      <testcase name="version" classname="version" status="run" time="0.1" />
    </testsuite>""")
    artifact = ArtifactLink(
        "Test execution artifacts",
        "test-results/id/stdout.log",
        "job/logs.zip",
        None,
        12,
        "c-api-execution",
        "qdb_c_api_tests",
    )
    report = build_report(
        "report",
        [("linux", tmp_path)],
        source_job_id="job",
        source_artifacts_by_job_id={"job": [artifact]},
    )
    assert report.ctest_execution_count == 0
    assert report.logical_test_count == 1
    assert report.duration_seconds == 0.1
    assert report.suites["qdb_c_api_tests"].test_files["c_api"].logical_tests[
        "version::version"
    ].executions["linux"].source_artifacts == [artifact]
