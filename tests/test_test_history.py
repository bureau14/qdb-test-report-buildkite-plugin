import io
import json
from urllib.parse import parse_qs, urlparse

import test_history


def snapshot(number, states):
    tests = []
    if states is not None:
        tests.append(
            {
                "identity": ["linux", "unit.xml", "suite", "class", "test"],
                "statuses": states,
                "duration": 1.0,
                "jobs": ["job"],
                "reasons": [],
            }
        )
    return {
        "build": {
            "id": f"uuid-{number}",
            "number": number,
            "web_url": f"https://buildkite.com/org/pipeline/{number}",
        },
        "xml_files": int(states is not None),
        "errors": [],
        "tests": tests,
    }


def row_for(*states):
    return test_history.analyze([snapshot(i, state) for i, state in enumerate(states)])["tests"][0]


def test_failures_recoveries_and_flakiness():
    row = row_for(["SUCCESSFUL"], ["FAILED"], ["ERRORED"])
    assert row["failed_since"]["number"] == 1
    assert row["failure_streak"] == 2
    assert row["failure_start_known"]
    assert not row["suspected_flaky"]
    assert not row["resolved"]
    row = row_for(["SUCCESSFUL"], ["FAILED"], ["SUCCESSFUL"])
    assert row["suspected_flaky"]
    assert row["resolved"]
    assert row["failure_rate"] == 1 / 3
    assert row["failed_since"] is None


def test_missing_and_skipped_do_not_resolve_or_extend_streak():
    for gap in (None, ["SKIPPED"]):
        row = row_for(["FAILED"], gap)
        assert not row["resolved"]
        assert row["measured_builds"] == 1
        assert row["failure_rate"] == 1
        row = row_for(["FAILED"], gap, ["FAILED"])
        assert row["failure_streak"] == 1
        assert not row["failure_start_known"]
        assert row["failed_since"]["number"] == 2


def test_initial_failure_is_lower_bound_and_one_transition_is_not_flaky():
    row = row_for(["FAILED"], ["FAILED"])
    assert not row["failure_start_known"]
    assert not row["new_failure"]
    row = row_for(["SUCCESSFUL"], ["FAILED"])
    assert row["new_failure"]
    assert not row["suspected_flaky"]


def test_mixed_outcomes_do_not_hide_failure():
    row = row_for(["SUCCESSFUL", "FAILED"])
    assert row["mixed_outcomes"]
    assert row["suspected_flaky"]
    assert row["latest"] == "FAILED"


def test_slowdown_requires_three_prior_passing_builds():
    snapshots = [snapshot(i, ["SUCCESSFUL"]) for i in range(4)]
    snapshots[-1]["tests"][0]["duration"] = 3.0
    row = test_history.analyze(snapshots)["tests"][0]
    assert row["slowdown"]
    assert row["duration_ratio"] == 3
    assert not test_history.analyze(snapshots[1:])["tests"][0]["slowdown"]


def test_platforms_are_independent():
    first = snapshot(1, ["FAILED"])
    second = snapshot(2, ["SUCCESSFUL"])
    second["tests"][0]["identity"][0] = "windows"
    rows = test_history.analyze([first, second])["tests"]
    assert len(rows) == 2
    assert all(not row["resolved"] and not row["suspected_flaky"] for row in rows)


def test_buildkite_paginates_filters_finished_builds_and_uses_uuid():
    requests = []

    def opener(request, timeout):
        query = parse_qs(urlparse(request.full_url).query)
        requests.append(query)
        assert request.get_header("Authorization") == "Bearer secret"
        assert timeout == 60
        assert query["branch"] == ["master"]
        page = int(query["page"][0])
        batches = {
            1: [{"id": "running", "branch": "master", "finished_at": None}],
            2: [{"id": "uuid", "number": 100, "branch": "master", "finished_at": "today"}],
            3: [],
        }
        return io.StringIO(json.dumps(batches[page]))

    builds = test_history.fetch_builds("org", "pipeline", "master", 2, "secret", opener)
    assert [build["id"] for build in builds] == ["uuid"]
    assert len(requests) == 3


def test_collect_snapshot_reuses_discovery_and_preserves_job_outcomes(tmp_path, monkeypatch):
    from report_downloads import DownloadedJobXml, JobXmlObject

    paths = []
    for job, result in (("job-1", "<failure message='bad'/>"), ("job-2", "")):
        path = tmp_path / (job + ".xml")
        path.write_text(
            '<testsuite name="suite"><testcase name="case">' + result + "</testcase></testsuite>",
            encoding="utf-8",
        )
        paths.append(
            DownloadedJobXml(JobXmlObject("linux", job, "key", "nested/unit.xml", 1), path)
        )

    def collect(**kwargs):
        assert kwargs["git_ref"] == "refs/heads/master"
        assert kwargs["build_id"] == "build-uuid"
        assert kwargs["bucket"] == "qdb-cicd-artifacts"
        return paths

    monkeypatch.setattr(test_history, "collect_full_scope_xml", collect)
    result = test_history.collect_snapshot(
        {"id": "build-uuid"}, "master", "s3://qdb-cicd-artifacts", "quasardb-build", tmp_path
    )
    assert len(result["tests"]) == 1
    assert result["tests"][0]["statuses"] == ["FAILED", "SUCCESSFUL"]
    assert result["tests"][0]["jobs"] == ["job-1", "job-2"]


def test_html_escapes_test_data_and_rejects_unsafe_links():
    item = snapshot(1, ["FAILED"])
    item["tests"][0]["identity"][-1] = "<script>alert(1)</script>"
    item["build"]["web_url"] = "javascript:alert(1)"
    output = test_history.render_history(test_history.analyze([item]))
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in output
    assert "javascript:" not in output


def test_empty_history():
    assert test_history.analyze([]) == {"builds": [], "summary": {}, "tests": []}


def test_main_writes_outputs_in_chronological_order(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILDKITE_API_TOKEN", "secret")
    monkeypatch.setattr("sys.argv", ["test_history.py", "--output", str(tmp_path)])
    monkeypatch.setattr(
        test_history,
        "fetch_builds",
        lambda *args: [{"id": "new", "number": 2}, {"id": "old", "number": 1}],
    )

    def collect(build, *args):
        return snapshot(build["number"], ["FAILED"] if build["id"] == "old" else ["SUCCESSFUL"])

    monkeypatch.setattr(test_history, "collect_snapshot", collect)
    test_history.main()
    data = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert [item["build"]["number"] for item in data["builds"]] == [1, 2]
    assert data["tests"][0]["resolved"]
    assert (tmp_path / "history.html").read_text(encoding="utf-8").startswith("<!doctype html>")
