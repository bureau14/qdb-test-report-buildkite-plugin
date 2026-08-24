import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"
sys.path.insert(0, str(TOOLS_DIR))


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def junit_xml(*testcases: str, suite_name: str = "suite") -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<testsuite tests="{count}" skipped="0" errors="0" failures="0" name="{suite_name}" time="1.25">
{body}
</testsuite>
""".format(count=len(testcases), suite_name=suite_name, body="\n".join(testcases))


def write_large_junit(path: Path, *, total: int, failed_every: int = 0) -> None:
    cases = []
    failures = 0
    for index in range(total):
        classname = f"suite.Class{index // 100}"
        name = f"test_{index:05d}"
        if failed_every and index % failed_every == 0:
            failures += 1
            cases.append(
                f'<testcase classname="{classname}" name="{name}" time="0.001">'
                f'<failure message="failed {index}">stack {index}</failure>'
                "</testcase>"
            )
        else:
            cases.append(f'<testcase classname="{classname}" name="{name}" time="0.001" />')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'<testsuite name="large" tests="{total}" failures="{failures}" errors="0" skipped="0">'
        + "".join(cases)
        + "</testsuite>",
        encoding="utf-8",
    )


def embedded_data(html: str):
    match = re.search(
        r'<script id="report-data" type="application/json">(.*?)</script>', html, re.DOTALL
    )
    assert match is not None
    return json.loads(match.group(1))


def test_dumps_embedded_json_uses_compact_separators():
    from html_report_writer import dumps_embedded_json

    assert dumps_embedded_json({"a": 1, "b": [2, 3]}) == '{"a":1,"b":[2,3]}'


def test_dumps_embedded_json_escapes_script_terminator():
    from html_report_writer import dumps_embedded_json

    rendered = dumps_embedded_json({"log": "x </script><script>alert(1)</script> y"})

    assert "</script>" not in rendered.lower()
    assert "\\u003c/script" in rendered.lower()


def test_dumps_embedded_json_escapes_html_sensitive_chars():
    from html_report_writer import dumps_embedded_json

    rendered = dumps_embedded_json({"value": "<tag>&stuff>"})

    assert "<" not in rendered
    assert ">" not in rendered
    assert "&" not in rendered


def test_junit_report_model_imports_without_datetime_utc(tmp_path):
    (tmp_path / "datetime.py").write_text(
        "from _datetime import date, datetime, time, timedelta, timezone, tzinfo\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(tmp_path), str(TOOLS_DIR)))

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import junit_report_model; print(junit_report_model.utc_now_iso())",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("Z")


def test_large_report_generation_preserves_summary_and_filters_tree(tmp_path):
    from junit_report_model import build_report
    from report_data import report_to_report_ui_data

    junit = tmp_path / "linux" / "large.xml"
    write_large_junit(junit, total=5000, failed_every=500)

    report = build_report("large", [("linux", junit)])
    full_execution = report_to_report_ui_data(report)[0]
    filtered_execution = report_to_report_ui_data(report, only_failures=True)[0]

    assert full_execution["summary"]["logicalTests"] == 5000
    assert full_execution["summary"]["platformExecutions"] == 5000
    assert full_execution["summary"]["statusCounts"] == {
        "FAILED": 10,
        "SUCCESSFUL": 4990,
    }
    assert filtered_execution["summary"] == full_execution["summary"]
    assert len(filtered_execution["testNodes"]) < len(full_execution["testNodes"])
    assert len(filtered_execution["testNodes"]) == 32


def test_build_report_preserves_suite_logical_and_platform_order(tmp_path):
    from junit_report_model import build_report

    linux = tmp_path / "linux"
    macos = tmp_path / "macos"
    write(
        linux / "a.xml",
        junit_xml(
            '<testcase classname="AuthTest" name="test_login_success" time="0.1"/>',
            '<testcase classname="AuthTest" name="test_expired_token" time="0.2"><failure message="expired">stack</failure></testcase>',
        ),
    )
    write(
        macos / "a.xml",
        junit_xml(
            '<testcase classname="AuthTest" name="test_expired_token" time="0.3"/>',
            '<testcase classname="CheckoutTest" name="test_payment_authorized" time="0.4"/>',
        ),
    )

    report = build_report(
        title="pipeline / build #1234",
        platform_specs=[("linux-x86_64", linux), ("macos-arm64", macos)],
        build_url="https://buildkite.example/builds/1234",
    )

    assert report.title == "pipeline / build #1234"
    assert report.platforms == ["linux-x86_64", "macos-arm64"]
    assert list(report.suites) == ["suite"]
    assert list(report.suites["suite"].test_files) == ["a"]
    logical_tests = list(report.suites["suite"].test_files["a"].logical_tests.values())
    assert [test.logical_id for test in logical_tests] == [
        "AuthTest::test_login_success",
        "AuthTest::test_expired_token",
        "CheckoutTest::test_payment_authorized",
    ]
    assert list(logical_tests[1].executions) == ["linux-x86_64", "macos-arm64"]
    assert logical_tests[1].executions["linux-x86_64"].status == "FAILED"
    assert logical_tests[1].executions["macos-arm64"].status == "SUCCESSFUL"
    assert report.raw_testcases == 4
    assert report.platform_execution_count == 4
    assert report.logical_status_counts == {"SUCCESSFUL": 2, "FAILED": 1}


def test_report_data_renders_buildkite_and_commit_urls_as_links(tmp_path):
    from junit_report_model import build_report
    from report_data import report_to_report_ui_data

    linux = tmp_path / "linux"
    write(
        linux / "a.xml",
        junit_xml('<testcase classname="Smoke" name="passes" time="0.1"/>'),
    )

    report = build_report(
        title="pipeline / build #1234",
        platform_specs=[("linux", linux)],
        build_url="https://buildkite.example/builds/1234",
        commit_url="https://github.com/acme/project/commit/0123456789abcdef",
    )

    execution = report_to_report_ui_data(report)[0]
    labels = execution["sections"][0]["blocks"][0]["content"]
    assert "buildkite-build-url:https://buildkite.example/builds/1234" not in labels

    kvp_blocks = [
        block
        for section in execution["sections"]
        for block in section["blocks"]
        if block["type"] == "kvp"
    ]
    metadata = {}
    for block in kvp_blocks:
        metadata.update(block["content"])

    assert metadata["Buildkite build"] == "link:https://buildkite.example/builds/1234"
    assert metadata["Git commit"] == "link:https://github.com/acme/project/commit/0123456789abcdef"

    leaf = next(node for node in execution["testNodes"] if node.get("status") == "SUCCESSFUL")
    assert leaf["source"] == [0, 0, 0, -1, -1, 0]
    assert execution["sourceTables"]["buildUrls"] == ["https://buildkite.example/builds/1234"]


def test_report_data_renders_artifacts_only_in_leaf_source_sections(tmp_path):
    from junit_report_model import ArtifactLink, build_report
    from report_data import report_to_report_ui_data

    linux = tmp_path / "linux"
    write(
        linux / "a.xml",
        junit_xml('<testcase classname="Smoke" name="passes" time="0.1"/>'),
    )

    report = build_report(
        title="pipeline / build #1234",
        platform_specs=[("linux", linux)],
        build_url="https://buildkite.example/builds/1234",
        source_job_id="job-1",
        source_artifacts_by_job_id={
            "job-1": [
                ArtifactLink(
                    name="Test logs",
                    relative_path="test-logs-1.tar.gz",
                    key="prefix/artifacts/test-logs/test-logs-1.tar.gz",
                    url="https://reports.example.com/prefix/artifacts/test-logs/test-logs-1.tar.gz",
                    size_bytes=123,
                )
            ]
        },
    )

    execution = report_to_report_ui_data(report)[0]
    root_metadata = {}
    for section in execution["sections"]:
        for block in section["blocks"]:
            if block["type"] == "kvp":
                root_metadata.update(block["content"])

    assert "Test logs" not in root_metadata
    assert "Artifact: Test logs" not in root_metadata

    leaf = next(node for node in execution["testNodes"] if node.get("status") == "SUCCESSFUL")
    source_artifact = leaf["sourceArtifacts"][0]
    assert source_artifact == {
        "name": "Test logs",
        "relativePath": "test-logs-1.tar.gz",
        "key": "prefix/artifacts/test-logs/test-logs-1.tar.gz",
        "url": "https://reports.example.com/prefix/artifacts/test-logs/test-logs-1.tar.gz",
        "sizeBytes": 123,
    }


def test_artifact_link_value_displays_uploaded_relative_path():
    from junit_report_model import ArtifactLink
    from report_data import artifact_value

    artifact = ArtifactLink(
        name="QDB test logs",
        relative_path="test_log/qdb_test_log_pid_90560.json",
        key="artifacts/test_log/qdb_test_log_pid_90560.json",
        url="https://reports.example/artifacts/test_log/qdb_test_log_pid_90560.json",
        size_bytes=123,
    )

    assert artifact_value(artifact) == (
        "link:https://reports.example/artifacts/test_log/qdb_test_log_pid_90560.json\n"
        "test_log/qdb_test_log_pid_90560.json"
    )


def test_qdb_process_id_metadata_matches_only_its_uploaded_json_log(tmp_path):
    from junit_report_model import ArtifactLink, build_report
    from report_data import report_to_report_ui_data

    linux = tmp_path / "linux"
    write(
        linux / "qdb_auth_test.xml",
        junit_xml(
            '<testcase name="qdb_test_process_id" time="0"><system-out>90560</system-out></testcase>',
            '<testcase classname="acl" name="data_size" time="0.1"/>',
            suite_name="qdb_unit_tests",
        ),
    )
    matching_log = ArtifactLink(
        name="QDB test logs",
        relative_path="test_log/qdb_test_log_pid_90560_1724412755000000000.json",
        key="artifacts/test_log/qdb_test_log_pid_90560_1724412755000000000.json",
        url="https://reports.example/qdb_test_log_pid_90560_1724412755000000000.json",
        size_bytes=123,
    )
    other_log = ArtifactLink(
        name="QDB test logs",
        relative_path="test_log/qdb_test_log_pid_81234_1724412755000000000.json",
        key="artifacts/test_log/qdb_test_log_pid_81234_1724412755000000000.json",
        url="https://reports.example/qdb_test_log_pid_81234_1724412755000000000.json",
        size_bytes=456,
    )

    report = build_report(
        "PID report",
        [("linux", linux)],
        source_job_id="job-1",
        source_artifacts_by_job_id={"job-1": [matching_log, other_log]},
    )

    assert report.raw_testcases == 2
    execution_model = (
        report.suites["qdb_unit_tests"]
        .test_files["qdb_auth_test"]
        .logical_tests["acl::data_size"]
        .executions["linux"]
    )
    assert execution_model.qdb_process_id == "90560"
    assert execution_model.source_artifacts == [matching_log]

    execution = report_to_report_ui_data(report)[0]
    leaves = [node for node in execution["testNodes"] if node.get("status") == "SUCCESSFUL"]
    assert [node["name"] for node in leaves] == [
        "qdb_test_process_id - linux",
        "data_size - linux",
    ]
    assert all(node["source"] == [0, 0, 0, -1, -1, -1, -1, 0] for node in leaves)
    assert execution["sourceTables"]["qdbProcessIds"] == ["90560"]
    for leaf in leaves:
        assert leaf["sourceArtifacts"] == [
            {
                "name": "QDB test logs",
                "relativePath": matching_log.relative_path,
                "key": matching_log.key,
                "url": matching_log.url,
                "sizeBytes": 123,
            }
        ]


def test_report_summary_ui_does_not_show_raw_testcases(tmp_path):
    from junit_report_model import build_report
    from report_data import report_to_report_ui_data

    linux = tmp_path / "linux"
    write(
        linux / "a.xml",
        junit_xml('<testcase classname="Smoke" name="passes" time="0.1"/>'),
    )

    execution = report_to_report_ui_data(
        build_report(title="pipeline", platform_specs=[("linux", linux)])
    )[0]

    kvp_blocks = [
        block
        for section in execution["sections"]
        for block in section["blocks"]
        if block["type"] == "kvp"
    ]
    metadata = {}
    for block in kvp_blocks:
        metadata.update(block["content"])

    assert "Raw testcases" not in metadata
    assert execution["summary"]["rawTestcases"] == 1


def test_report_data_does_not_include_infrastructure_section(tmp_path):
    from junit_report_model import build_report
    from report_data import report_to_report_ui_data

    linux = tmp_path / "linux"
    write(
        linux / "a.xml",
        junit_xml('<testcase classname="Smoke" name="passes" time="0.1"/>'),
    )

    report = build_report(title="pipeline", platform_specs=[("linux", linux)])
    execution = report_to_report_ui_data(report)[0]

    section_titles = [section["title"] for section in execution["sections"]]
    assert "Infrastructure" not in section_titles

    section_text = json.dumps(execution["sections"])
    assert "Hostname" not in section_text
    assert "junit-html-report-tool" not in section_text
    assert "Username" not in section_text
    assert "mixed-platform" not in section_text


def test_build_report_supports_glob_platform_paths(tmp_path, monkeypatch):
    from junit_report_model import build_report

    write(
        tmp_path / "linux-core2-release" / "build" / "Release" / "test-reports" / "qdb.xml",
        junit_xml(
            '<testcase classname="Smoke" name="passes" time="0.01"/>',
            '<testcase classname="Smoke" name="skips" time="0.02"><skipped message="disabled"/></testcase>',
            suite_name="qdb_integration_tests",
        ),
    )

    monkeypatch.chdir(tmp_path)
    report = build_report(
        "glob report",
        [("linux-core2-release", Path("**/test-reports/*.xml"))],
    )

    assert report.total_files == 1
    assert report.raw_testcases == 2
    assert list(report.suites) == ["qdb_integration_tests"]
    assert report.status_counts["SUCCESSFUL"] == 1
    assert report.status_counts["SKIPPED"] == 1


def test_build_report_records_malformed_xml_files_and_skips_empty_files(tmp_path, capsys):
    from junit_report_model import build_report

    linux = tmp_path / "linux"
    write(
        linux / "valid.xml",
        junit_xml('<testcase classname="Smoke" name="passes" time="0.01"/>'),
    )
    write(linux / "empty.xml", "")
    write(linux / "broken.xml", "<testsuite>")

    report = build_report("dirty xml", [("linux", linux)])

    assert report.total_files == 3
    assert report.raw_testcases == 1
    assert report.status_counts["SUCCESSFUL"] == 1
    assert report.malformed_junit_xml == [
        {
            "file": str(linux / "broken.xml"),
            "platform": "linux",
            "error": "no element found: line 1, column 11",
        }
    ]
    stderr = capsys.readouterr().err
    assert "skipping empty JUnit XML file" in stderr
    assert "file=" in stderr and "empty.xml" in stderr
    assert "skipping malformed JUnit XML file" in stderr
    assert "broken.xml" in stderr


def test_build_report_keeps_source_file_aware_identity_and_worst_duplicate_status(
    tmp_path,
):
    from junit_report_model import build_report

    linux = tmp_path / "linux"
    write(
        linux / "api" / "shared.xml",
        junit_xml('<testcase classname="add" name="returns_invalid_argument" time="0.1"/>'),
    )
    write(
        linux / "cli" / "shared.xml",
        junit_xml('<testcase classname="add" name="returns_invalid_argument" time="0.2"/>'),
    )
    write(
        linux / "duplicates.xml",
        junit_xml(
            '<testcase classname="Smoke" name="duplicate" time="0.01"/>',
            '<testcase classname="Smoke" name="duplicate" time="0.02"><failure message="failure"><![CDATA[- message: duplicate failed later]]></failure></testcase>',
        ),
    )

    report = build_report("duplicates", [("linux", linux)])

    test_files = report.suites["suite"].test_files
    assert set(test_files) == {"shared", "duplicates"}
    shared = test_files["shared"].logical_tests
    duplicates = test_files["duplicates"].logical_tests
    assert list(shared) == ["add::returns_invalid_argument"]
    assert list(duplicates) == ["Smoke::duplicate"]
    duplicate_execution = duplicates["Smoke::duplicate"].executions["linux"]
    assert duplicate_execution.status == "FAILED"
    assert duplicate_execution.reason == "duplicate failed later"
    assert report.duplicates_seen == 2
    assert report.duplicates_replaced == 1


def test_report_ui_groups_suite_test_file_classname_test_and_platform_without_sorting(tmp_path):
    from junit_report_model import build_report
    from report_data import report_to_report_ui_data

    linux = tmp_path / "linux"
    write(
        linux / "build" / "Release" / "test-reports" / "qdb_regression_test.xml",
        junit_xml(
            '<testcase classname="BoostSuite" name="same_name" time="0.1"/>',
            '<testcase classname="OtherSuite" name="other_test" time="0.3"/>',
        ),
    )
    write(
        linux / "build" / "Release" / "test-reports" / "qdb_aggregation_test.xml",
        junit_xml('<testcase classname="BoostSuite" name="same_name" time="0.2"/>'),
    )

    execution = report_to_report_ui_data(build_report("boost", [("linux", linux)]))[0]
    nodes = {node["id"]: node for node in execution["testNodes"]}
    suite = next(node for node in execution["testNodes"] if node["name"] == "suite")
    file_ids = execution["children"][suite["id"]]["ids"]
    file_names = [nodes[file_id]["name"] for file_id in file_ids]
    assert file_names == ["qdb_regression_test", "qdb_aggregation_test"]

    regression_class_ids = execution["children"][file_ids[0]]["ids"]
    assert [nodes[class_id]["name"] for class_id in regression_class_ids] == [
        "BoostSuite",
        "OtherSuite",
    ]
    aggregation_class_ids = execution["children"][file_ids[1]]["ids"]
    assert [nodes[class_id]["name"] for class_id in aggregation_class_ids] == ["BoostSuite"]

    first_test_ids = execution["children"][regression_class_ids[0]]["ids"]
    assert [nodes[test_id]["name"] for test_id in first_test_ids] == ["same_name"]
    platform_ids = execution["children"][first_test_ids[0]]["ids"]
    assert [nodes[platform_id]["name"] for platform_id in platform_ids] == ["same_name - linux"]

    second_test_ids = execution["children"][regression_class_ids[1]]["ids"]
    assert [nodes[test_id]["name"] for test_id in second_test_ids] == ["other_test"]

    assert execution["summary"]["logicalTests"] == 3
    assert execution["summary"]["structuralContainers"] == 9


def test_build_report_strips_buildkite_job_uuid_from_full_scope_source_identity(
    tmp_path,
):
    from junit_report_model import build_report
    from report_data import report_to_report_ui_data

    linux = tmp_path / "linux"
    macos = tmp_path / "macos"
    linux_uuid = "019e20db-6251-4594-8925-2d4c671fa2e2"
    macos_uuid = "119e20db-6251-4594-8925-2d4c671fa2e3"
    write(
        linux / linux_uuid / "linux-core2-release-py314" / "pytest.xml",
        junit_xml(
            '<testcase classname="Smoke" name="same_test" time="0.1"><error message="error"/></testcase>'
        ),
    )
    write(
        macos / macos_uuid / "macos-arm64-release-py314" / "pytest.xml",
        junit_xml(
            '<testcase classname="Smoke" name="same_test" time="0.2"><error message="error"/></testcase>'
        ),
    )

    report = build_report(
        "full",
        [("linux-core2-release-py314", linux), ("macos-arm64-release-py314", macos)],
        build_url="https://buildkite.example/acme/project/builds/123",
    )

    logical = report.suites["suite"].test_files["pytest"].logical_tests
    assert list(logical) == ["Smoke::same_test"]
    assert list(logical["Smoke::same_test"].executions) == [
        "linux-core2-release-py314",
        "macos-arm64-release-py314",
    ]
    assert report.logical_test_count == 1
    assert report.platform_execution_count == 2

    execution = report_to_report_ui_data(report)[0]
    node_names = [node["name"] for node in execution["testNodes"]]
    assert "Smoke" in node_names
    assert "same_test" in node_names
    assert not any(linux_uuid in name or macos_uuid in name for name in node_names)
    source_metadata = [node["source"] for node in execution["testNodes"] if node.get("source")]
    xml_table = execution["sourceTables"]["xmls"]
    target_table = execution["sourceTables"]["targets"]
    assert any(xml_table[metadata[2]] == "pytest.xml" for metadata in source_metadata)
    assert not any(
        linux_uuid in xml_table[metadata[2]]
        or macos_uuid in xml_table[metadata[2]]
        or linux_uuid in target_table[metadata[0]]
        or macos_uuid in target_table[metadata[0]]
        for metadata in source_metadata
    )

    source_metadata = [
        node["source"]
        for node in execution["testNodes"]
        if node["name"] == "same_test - linux-core2-release-py314"
    ]
    assert source_metadata == [[0, 0, 0, 0, 0, 0]]
    assert execution["sourceTables"] == {
        "targets": ["linux-core2-release-py314", "macos-arm64-release-py314"],
        "suites": ["suite"],
        "xmls": ["pytest.xml"],
        "buildUrls": ["https://buildkite.example/acme/project/builds/123"],
        "jobUrls": [
            f"https://buildkite.example/acme/project/builds/123#{linux_uuid}",
            f"https://buildkite.example/acme/project/builds/123#{macos_uuid}",
        ],
        "jobIds": [linux_uuid, macos_uuid],
        "xmlUrls": [],
    }


def test_report_ui_data_exposes_true_execution_counts_for_custom_header(tmp_path):
    from junit_report_model import build_report
    from report_data import report_to_report_ui_data

    linux = tmp_path / "linux"
    macos = tmp_path / "macos"
    write(
        linux / "junit.xml",
        junit_xml(
            '<testcase classname="Smoke" name="passes" time="0.01"/>',
            '<testcase classname="Smoke" name="fails" time="0.02"><failure message="failure"/></testcase>',
        ),
    )
    write(
        macos / "junit.xml",
        junit_xml(
            '<testcase classname="Smoke" name="passes" time="0.03"/>',
            '<testcase classname="Smoke" name="fails" time="0.04"><skipped message="disabled"/></testcase>',
        ),
    )

    execution = report_to_report_ui_data(
        build_report("counts", [("linux", linux), ("macos", macos)])
    )[0]

    assert execution["summary"] == {
        "rawTestcases": 4,
        "suites": 1,
        "logicalTests": 2,
        "platformExecutions": 4,
        "targets": 2,
        "resolvedPlatforms": ["linux", "macos"],
        "structuralContainers": 5,
        "statusCounts": {"SUCCESSFUL": 2, "SKIPPED": 1, "FAILED": 1},
        "logicalStatusCounts": {"SUCCESSFUL": 1, "FAILED": 1},
        "rootStatus": "FAILED",
    }
    assert len(execution["testNodes"]) == 9
    assert execution["tagTables"] == {
        "suites": ["suite"],
        "platforms": ["linux", "macos"],
        "classnames": ["Smoke"],
        "testNames": ["passes", "fails"],
        "logicalIds": ["Smoke::passes", "Smoke::fails"],
    }
    logical_fails = next(node for node in execution["testNodes"] if node["name"] == "fails")
    assert logical_fails["sections"] == []
    assert logical_fails["tags"] == [1, 0, 0, 1, 1, [0], [], [1]]
    suite = next(node for node in execution["testNodes"] if node["name"] == "suite")
    assert suite["sections"] == []
    assert suite["tags"] == [0, 0]


def test_successful_leaf_uses_compact_source_metadata_instead_of_tags(tmp_path):
    from junit_report_model import build_report
    from report_data import report_to_report_ui_data

    linux = tmp_path / "linux"
    write(
        linux / "junit.xml",
        junit_xml('<testcase classname="Smoke" name="passes" time="0.01"/>'),
    )

    execution = report_to_report_ui_data(build_report("compact", [("linux", linux)]))[0]
    leaf = next(node for node in execution["testNodes"] if node.get("status") == "SUCCESSFUL")

    assert leaf["name"] == "passes - linux"
    assert leaf["source"] == [0, 0, 0]
    assert execution["sourceTables"] == {
        "targets": ["linux"],
        "suites": ["suite"],
        "xmls": ["junit.xml"],
        "buildUrls": [],
        "jobUrls": [],
        "jobIds": [],
        "xmlUrls": [],
    }
    assert leaf["sections"] == []


def test_platform_leaves_include_test_name_and_deduplicated_xml_urls(tmp_path):
    from junit_report_model import build_report
    from report_data import report_to_report_ui_data

    linux = write(
        tmp_path / "linux" / "job-1" / "results.xml",
        junit_xml(
            '<testcase classname="Smoke" name="same_test" time="0.01"/>',
            '<testcase classname="Smoke" name="another_test" time="0.01"/>',
        ),
    )
    macos = write(
        tmp_path / "macos" / "job-2" / "results.xml",
        junit_xml('<testcase classname="Smoke" name="same_test" time="0.01"/>'),
    )
    report = build_report(
        "xml links",
        [("linux", linux.parent.parent), ("macos", macos.parent.parent)],
        build_url="https://buildkite.example/builds/1",
        xml_source_links={
            linux.resolve(): "https://reports.example.com/original/linux-results.xml",
            macos.resolve(): "https://reports.example.com/original/macos-results.xml",
        },
    )

    execution = report_to_report_ui_data(report)[0]
    leaves = [node for node in execution["testNodes"] if node.get("status")]
    assert [node["name"] for node in leaves] == [
        "same_test - linux",
        "same_test - macos",
        "another_test - linux",
    ]
    assert "same_test" in [node["name"] for node in execution["testNodes"]]
    assert execution["sourceTables"]["xmlUrls"] == [
        "https://reports.example.com/original/linux-results.xml",
        "https://reports.example.com/original/macos-results.xml",
    ]
    assert [node["source"][-1] for node in leaves] == [0, 1, 0]


def test_non_success_leaf_preserves_source_metadata_without_implicit_source(tmp_path):
    from junit_report_model import build_report
    from report_data import report_to_report_ui_data

    linux = tmp_path / "linux"
    write(
        linux / "junit.xml",
        junit_xml(
            '<testcase classname="Smoke" name="fails" time="0.01">'
            '<failure message="failure"><![CDATA[- message: failed specifically]]></failure>'
            "</testcase>"
        ),
    )

    execution = report_to_report_ui_data(build_report("compact", [("linux", linux)]))[0]
    leaf = next(node for node in execution["testNodes"] if node.get("status") == "FAILED")
    assert leaf["source"] == [0, 0, 0]
    assert execution["sourceTables"] == {
        "targets": ["linux"],
        "suites": ["suite"],
        "xmls": ["junit.xml"],
        "buildUrls": [],
        "jobUrls": [],
        "jobIds": [],
        "xmlUrls": [],
    }
    assert "source:junit" not in json.dumps(leaf["sections"])
    assert "Reason" in [section["title"] for section in leaf["sections"]]


def test_report_ui_data_has_valid_tree_leaf_statuses_and_failure_details(tmp_path):
    from junit_report_model import build_report
    from report_data import report_to_report_ui_data

    linux = tmp_path / "linux"
    write(
        linux / "failure.xml",
        junit_xml(
            """<testcase classname="CrossPlatform" name="same_test" time="0.1">
<failure message="failure"><![CDATA[- message: linux failed specifically]]></failure>
<system-err><![CDATA[stderr details]]></system-err>
</testcase>""",
            suite_name="cross-platform-suite",
        ),
    )

    data = report_to_report_ui_data(
        build_report("two visible failures", [("linux", linux)]), execution_name="demo"
    )

    execution = data[0]
    nodes_by_id = {node["id"]: node for node in execution["testNodes"]}
    assert execution["name"] == "demo"
    assert all(root_id in nodes_by_id for root_id in execution["roots"])
    assert all(
        child_id in nodes_by_id
        for children in execution["children"].values()
        for child_id in children["ids"]
    )

    failed_leaves = [node for node in execution["testNodes"] if node.get("status") == "FAILED"]
    assert [node["name"] for node in failed_leaves] == ["same_test - linux"]
    failed_leaf = failed_leaves[0]
    section_titles = [section["title"] for section in failed_leaf["sections"]]
    assert "Reason" in section_titles
    assert any(
        block.get("type") == "p" and "linux failed specifically" in block.get("content", "")
        for section in failed_leaf["sections"]
        for block in section.get("blocks", [])
    )
    pre_blocks = []
    for section in failed_leaf["sections"]:
        for block in section.get("blocks", []):
            content = block.get("content")
            if not isinstance(content, list):
                continue
            for subsection in content:
                if isinstance(subsection, dict):
                    pre_blocks.extend(subsection.get("blocks", []))
    assert any(
        block.get("type") == "pre" and "stderr details" in block.get("content", "")
        for block in pre_blocks
    )
    assert all(
        "status" not in node
        for node in execution["testNodes"]
        if node["name"] != "same_test - linux"
    )


def test_html_writer_injects_safe_json_and_rejects_bad_templates(tmp_path):
    from html_report_writer import PLACEHOLDER, render_html

    template = tmp_path / "template.html"
    template.write_text(f"<html><body>{PLACEHOLDER}</body></html>", encoding="utf-8")

    html = render_html([{"payload": "</script><!--"}], template)

    assert '<script id="report-data" type="application/json">' in html
    assert "globalThis.testExecutions =" not in html
    assert PLACEHOLDER not in html
    assert "</script><!--" not in html
    assert r"\u003c/script\u003e" in html

    bad_template = tmp_path / "bad.html"
    bad_template.write_text("<html></html>", encoding="utf-8")
    try:
        render_html([], bad_template)
    except ValueError as exc:
        assert "Expected exactly one" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected bad template to fail")


def test_cli_writes_self_contained_html_from_repeated_platform_arguments(tmp_path):
    linux = tmp_path / "linux" / "junit.xml"
    macos = tmp_path / "macos" / "junit.xml"
    output = tmp_path / "junit-report.html"
    write(linux, junit_xml('<testcase classname="Smoke" name="passes" time="0.01"/>'))
    write(
        macos,
        junit_xml(
            '<testcase classname="Smoke" name="passes" time="0.02"><skipped message="disabled"/></testcase>'
        ),
    )

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "junit_html_report.py"),
            "--title",
            "cli demo",
            "--platform",
            f"linux={linux}",
            "--platform",
            f"macos={macos}",
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert output.exists()
    html = output.read_text(encoding="utf-8")
    assert '<script id="report-data" type="application/json">' in html
    assert "globalThis.testExecutions =" not in html
    assert "tests per target" in html
    assert "target" in html
    assert "logical tests" not in html
    assert "containers" not in html
    assert "tests/containers" not in html
    assert "<!-- TEST_REPORT_DATA -->" not in html
    data = embedded_data(html)
    node_names = [node["name"] for node in data[0]["testNodes"]]
    assert "Smoke" in node_names
    assert "passes" in node_names
    assert "passes - linux" in node_names
    assert "passes - macos" in node_names
    assert "INFO  Wrote HTML report" in result.stderr
    assert "Final summary:" in result.stderr


def test_cli_writes_summary_json(tmp_path):
    junit = tmp_path / "junit.xml"
    output = tmp_path / "report.html"
    summary_path = tmp_path / "summary.json"
    write(
        junit,
        junit_xml(
            '<testcase classname="S" name="p1" time="0"/>',
            '<testcase classname="S" name="p2" time="0"/>',
            '<testcase classname="S" name="f" time="0"><failure message="f"/></testcase>',
        ),
    )

    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "junit_html_report.py"),
            "--title",
            "test title",
            "--platform",
            f"linux={junit}",
            "--output",
            str(output),
            "--summary-json",
            str(summary_path),
        ],
        check=True,
    )

    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary == {
        "raw_testcases": 3,
        "suites": 1,
        "logical_tests": 3,
        "platform_executions": 3,
        "targets": 1,
        "platforms": ["linux"],
        "resolved_platforms": ["linux"],
        "status_counts": {"SUCCESSFUL": 2, "FAILED": 1},
        "logical_status_counts": {"SUCCESSFUL": 2, "FAILED": 1},
        "root_status": "FAILED",
        "malformed_junit_xml": [],
    }


def test_cli_fail_on_test_failures_returns_64_for_failures_and_errors(tmp_path):
    junit = tmp_path / "junit.xml"
    output = tmp_path / "report.html"
    write(
        junit,
        junit_xml(
            '<testcase classname="S" name="f" time="0"><failure message="f"/></testcase>',
            '<testcase classname="S" name="e" time="0"><error message="e"/></testcase>',
        ),
    )

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "junit_html_report.py"),
            "--title",
            "t",
            "--platform",
            f"l={junit}",
            "--output",
            str(output),
            "--fail-on-test-failures",
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 64
    assert "2 failed/errored test execution" in result.stderr


def test_cli_only_failures_filters_tree(tmp_path):
    junit = tmp_path / "junit.xml"
    output = tmp_path / "report.html"
    write(
        junit,
        junit_xml(
            '<testcase classname="S" name="p" time="0"/>',
            '<testcase classname="S" name="f" time="0"><failure message="f"/></testcase>',
        ),
    )

    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "junit_html_report.py"),
            "--title",
            "t",
            "--platform",
            f"l={junit}",
            "--output",
            str(output),
            "--only-failures",
        ],
        check=True,
    )

    data = embedded_data(output.read_text(encoding="utf-8"))
    node_names = [node["name"] for node in data[0]["testNodes"]]
    assert "S" in node_names
    assert "f" in node_names
    assert "junit.xml::S::p" not in node_names
    assert data[0]["summary"]["statusCounts"] == {"SUCCESSFUL": 1, "FAILED": 1}
    assert data[0]["summary"]["logicalStatusCounts"] == {"SUCCESSFUL": 1, "FAILED": 1}


def test_report_ui_data_can_filter_only_failures(tmp_path):
    from junit_report_model import build_report
    from report_data import report_to_report_ui_data

    linux = tmp_path / "linux"
    write(
        linux / "junit.xml",
        junit_xml(
            '<testcase classname="Smoke" name="passes" time="0.01"/>',
            '<testcase classname="Smoke" name="fails" time="0.02"><failure message="failure"/></testcase>',
            '<testcase classname="Smoke" name="skipped" time="0.03"><skipped message="skipped"/></testcase>',
        ),
    )

    report = build_report("filter test", [("linux", linux)])

    # Baseline: 3 test nodes (execution leaves) + 3 logical + 1 classname + 1 test file + 1 suite = 9 nodes
    full_execution = report_to_report_ui_data(report)[0]
    assert full_execution["summary"]["platformExecutions"] == 3
    assert len(full_execution["testNodes"]) == 9

    # Only failures: should skip SUCCESSFUL and SKIPPED
    filtered_execution = report_to_report_ui_data(report, only_failures=True)[0]

    # Summary should still show true totals
    assert filtered_execution["summary"]["platformExecutions"] == 3
    assert filtered_execution["summary"]["statusCounts"] == {
        "SUCCESSFUL": 1,
        "FAILED": 1,
        "SKIPPED": 1,
    }
    assert filtered_execution["summary"]["logicalStatusCounts"] == {
        "SUCCESSFUL": 1,
        "FAILED": 1,
        "SKIPPED": 1,
    }

    # But testNodes should only contain the FAILED one and its parents
    node_names = [node["name"] for node in filtered_execution["testNodes"]]
    assert "fails - linux" in node_names
    assert "Smoke" in node_names
    assert "fails" in node_names
    assert "passes" not in node_names
    assert "skipped" not in node_names

    # 1 suite + 1 test file + 1 classname + 1 logical + 1 execution leaf = 5 nodes
    assert len(filtered_execution["testNodes"]) == 5
