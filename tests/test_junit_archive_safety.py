import io
import json
import re
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest
from object_store import ObjectAuth, StoreConfig
from report_downloads import JobXmlObject, collect_full_scope_xml


@pytest.fixture
def archive_store(monkeypatch, tmp_path):
    objects = []
    payloads = {}

    def add(job, members=None, payload=None):
        if payload is None:
            assert members is not None
            buffer = io.BytesIO()
            with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
                for name, content in members:
                    archive.writestr(name, content)
            payload = buffer.getvalue()
        key = f"prefix/linux/jobs/{job}/xml/junit.zip"
        objects.append(JobXmlObject("linux", job, key, "junit.zip", len(payload)))
        payloads[key] = payload
        return objects[-1]

    def download(cfg, auth, bucket, key, local_path, **kwargs):
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(payloads[key])

    monkeypatch.setattr("report_downloads.find_job_xml_objects", lambda **kwargs: objects)
    monkeypatch.setattr("report_downloads.create_s3_client", lambda *args: object())
    monkeypatch.setattr("report_downloads.download_file", download)
    kwargs = {
        "cfg": StoreConfig("s3", "s3://bucket", artifacts_domain="reports.example.com"),
        "auth": ObjectAuth(),
        "bucket": "bucket",
        "destination_prefix": "prefix",
        "project_id": "p",
        "git_ref": "main",
        "build_id": "b",
        "output_dir": tmp_path / "stage",
        "download_parallel": 1,
    }
    return add, kwargs


def test_corrupt_archive_does_not_discard_valid_jobs(archive_store):
    add, kwargs = archive_store
    add("good", [("results.xml", '<testsuite><testcase name="passes"/></testsuite>')])
    add("bad", payload=b"not a zip")
    result = collect_full_scope_xml(**kwargs)
    assert [item.job_id for item in result] == ["good"]


def test_archive_error_preserves_provenance(archive_store):
    add, kwargs = archive_store
    add("bad", payload=b"not a zip")
    errors = []
    assert collect_full_scope_xml(**kwargs, archive_errors=errors) == []
    assert len(errors) == 1
    assert errors[0]["key"] == "prefix/linux/jobs/bad/xml/junit.zip"
    assert errors[0]["job_id"] == "bad"
    assert errors[0]["platform"] == "linux"
    assert errors[0]["url"] == "https://reports.example.com/prefix/linux/jobs/bad/xml/junit.zip"
    assert "zip" in errors[0]["error"].lower()


def test_corrupt_utf8_archive_names_do_not_discard_valid_jobs(archive_store):
    add, kwargs = archive_store
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("é.xml", "invalid-name")
    payload = buffer.getvalue().replace("é.xml".encode(), b"\xff\xff.xml")
    add("bad", payload=payload)
    add("good", [("results.xml", "valid")])
    errors = []
    result = collect_full_scope_xml(**kwargs, archive_errors=errors)
    assert [item.job_id for item in result] == ["good"]
    assert len(errors) == 1


@pytest.mark.parametrize(
    ("limit", "value", "members"),
    [
        ("MAX_JUNIT_ARCHIVE_BYTES", 1, [("one.xml", "x")]),
        ("MAX_JUNIT_ARCHIVE_MEMBERS", 1, [("one.xml", "x"), ("two.xml", "x")]),
        ("MAX_JUNIT_MEMBER_BYTES", 4, [("one.xml", "12345")]),
        ("MAX_JUNIT_EXTRACTED_BYTES", 4, [("one.xml", "123"), ("two.xml", "45")]),
    ],
)
def test_legacy_archive_limits_do_not_reject_valid_xml(
    monkeypatch, archive_store, limit, value, members
):
    add, kwargs = archive_store
    monkeypatch.setattr("report_downloads." + limit, value, raising=False)
    add("good", members)
    errors = []
    result = collect_full_scope_xml(**kwargs, archive_errors=errors)
    assert [(item.relative_path, item.local_path.read_text()) for item in result] == members
    assert errors == []


def test_legacy_report_budget_does_not_discard_jobs(monkeypatch, archive_store):
    add, kwargs = archive_store
    monkeypatch.setattr("report_downloads.MAX_JUNIT_REPORT_BYTES", 4, raising=False)
    add("first", [("one.xml", "123")])
    add("second", [("two.xml", "45")])
    errors = []
    result = collect_full_scope_xml(**kwargs, archive_errors=errors)
    assert [item.job_id for item in result] == ["first", "second"]
    assert errors == []


def test_parallel_jobs_are_not_subject_to_legacy_report_budget(monkeypatch, archive_store):
    add, kwargs = archive_store
    monkeypatch.setattr("report_downloads.MAX_JUNIT_REPORT_BYTES", 4, raising=False)
    for job in ("one", "two", "three"):
        add(job, [("results.xml", "12")])
    kwargs["download_parallel"] = 3
    errors = []
    result = collect_full_scope_xml(**kwargs, archive_errors=errors)
    assert [item.job_id for item in result] == ["one", "two", "three"]
    assert sum(item.local_path.stat().st_size for item in result) == 6
    assert errors == []


def test_actual_archive_size_does_not_gate_extraction(monkeypatch, archive_store):
    from dataclasses import replace

    add, kwargs = archive_store
    obj = add("good", [("results.xml", "x")])
    monkeypatch.setattr("report_downloads.MAX_JUNIT_ARCHIVE_BYTES", 1, raising=False)
    monkeypatch.setattr(
        "report_downloads.find_job_xml_objects", lambda **kwargs: [replace(obj, size_bytes=1)]
    )
    errors = []
    result = collect_full_scope_xml(**kwargs, archive_errors=errors)
    assert result[0].local_path.read_text() == "x"
    assert errors == []
    assert not (kwargs["output_dir"] / "linux/good/.junit.zip").exists()


@pytest.mark.parametrize("invalid", ["duplicate", "empty", "conflicting"])
def test_invalid_archives_are_isolated(archive_store, invalid):
    add, kwargs = archive_store
    if invalid == "duplicate":
        with pytest.warns(UserWarning, match="Duplicate name"):
            add("bad", [("results.xml", "one"), ("results.xml", "two")])
    elif invalid == "empty":
        add("bad", [])
    else:
        add("bad", [("first.xml", "one"), ("first.xml/second.xml", "two")])
    add("good", [("results.xml", "valid")])
    errors = []
    result = collect_full_scope_xml(**kwargs, archive_errors=errors)
    assert [item.job_id for item in result] == ["good"]
    assert len(errors) == 1
    assert list((kwargs["output_dir"] / "linux/bad").rglob("*.xml")) == []


def test_archive_extraction_streams_members(monkeypatch, archive_store):
    add, kwargs = archive_store
    add("good", [("results.xml", "x" * 200_000)])

    def whole_member_read(*args, **kwargs):
        pytest.fail("extraction must not allocate a whole uncompressed member")

    monkeypatch.setattr(ZipFile, "read", whole_member_read)
    result = collect_full_scope_xml(**kwargs)
    assert result[0].local_path.stat().st_size == 200_000


def test_xml_member_directory_does_not_collide_with_download_staging(archive_store):
    add, kwargs = archive_store
    add("good", [(".junit.zip/results.xml", "valid")])
    result = collect_full_scope_xml(**kwargs)
    assert len(result) == 1
    assert result[0].relative_path == ".junit.zip/results.xml"
    assert result[0].local_path.read_text() == "valid"


def test_crc_failure_removes_partial_job_and_preserves_valid_jobs(archive_store):
    add, kwargs = archive_store
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_STORED) as archive:
        archive.writestr("first.xml", "good")
        archive.writestr("second.xml", "bad-content")
    payload = buffer.getvalue().replace(b"bad-content", b"BAD-content", 1)
    add("bad", payload=payload)
    add("good", [("valid.xml", "x" * 15)])
    errors = []
    result = collect_full_scope_xml(**kwargs, archive_errors=errors)
    assert [item.job_id for item in result] == ["good"]
    assert "CRC" in errors[0]["error"]
    assert list((kwargs["output_dir"] / "linux" / "bad").rglob("*.xml")) == []


def test_xml_above_64_mib_generates_complete_report(monkeypatch, archive_store, tmp_path):
    import shutil

    from junit_html_report import generate_html_report

    add, kwargs = archive_store
    obj = add("large", [("results.xml", "placeholder")])
    archive_path = tmp_path / "large.zip"
    with (
        ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive,
        archive.open("results.xml", "w") as output,
    ):
        output.write(b'<testsuite><testcase name="large"><system-out>')
        # Stream a real member above the former cap without a giant fixture string.
        for _ in range(65):
            output.write(b"x" * (1024 * 1024))
        output.write(b'</system-out></testcase><testcase name="last"/></testsuite>')

    def download(cfg, auth, bucket, key, local_path, **kwargs):
        assert key == obj.key
        shutil.copyfile(archive_path, local_path)

    monkeypatch.setattr("report_downloads.download_file", download)
    errors = []
    result = collect_full_scope_xml(**kwargs, archive_errors=errors)
    assert len(result) == 1
    assert result[0].local_path.stat().st_size > 64 * 1024 * 1024
    assert errors == []

    html_path = tmp_path / "index.html"
    summary_path = tmp_path / "summary.json"
    assert (
        generate_html_report(
            title="Large archive",
            platform_specs=[("linux", kwargs["output_dir"] / "linux")],
            output=html_path,
            summary_json=summary_path,
            junit_archive_errors=errors,
        )
        == 0
    )
    summary = json.loads(summary_path.read_text())
    assert summary["logical_tests"] == 2
    assert summary["status_counts"]["SUCCESSFUL"] == 2
    assert summary["root_status"] == "SUCCESSFUL"
    assert not summary.get("junit_archive_errors")
    html = html_path.read_text()
    assert '"name":"last - linux"' in html


def test_archive_above_10000_members_retains_all_xml(archive_store):
    add, kwargs = archive_store
    members = [(f"{index}.xml", "valid") for index in range(10_001)]
    add("many", members)
    errors = []
    result = collect_full_scope_xml(**kwargs, archive_errors=errors)
    assert [(item.relative_path, item.local_path.read_text()) for item in result] == members
    assert errors == []


@pytest.mark.parametrize("member", ["../escape.xml", "/escape.xml", "C:/escape.xml"])
def test_unsafe_archive_is_reported_without_losing_other_jobs(archive_store, member):
    add, kwargs = archive_store
    add("bad", [("first.xml", "valid"), (member, "invalid")])
    add("good", [("results.xml", "valid")])
    errors = []
    result = collect_full_scope_xml(**kwargs, archive_errors=errors)
    assert [item.job_id for item in result] == ["good"]
    assert "Unsafe" in errors[0]["error"]
    assert list((kwargs["output_dir"] / "linux" / "bad").rglob("*.xml")) == []


@pytest.mark.parametrize("has_valid_job", [True, False])
@pytest.mark.parametrize("public_url", [True, False])
def test_main_publishes_archive_errors_with_valid_results(
    monkeypatch, archive_store, has_valid_job, public_url
):
    import test_report_plugin
    from object_store import PublishedObject

    add, _ = archive_store
    add("bad", payload=b"not a zip")
    if has_valid_job:
        add("good", [("results.xml", '<testsuite><testcase name="passes"/></testsuite>')])
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE", "Tests")
    monkeypatch.setenv("BUILDKITE_PIPELINE_SLUG", "project")
    monkeypatch.setenv("BUILDKITE_BUILD_ID", "build")
    monkeypatch.setenv("BUILDKITE_BRANCH", "main")
    context = test_report_plugin.ObjectStoreContext(
        StoreConfig(
            "s3", "s3://bucket", artifacts_domain="reports.example.com" if public_url else None
        ),
        ObjectAuth(),
        "bucket",
        "prefix",
    )
    monkeypatch.setattr(test_report_plugin, "resolve_object_store_context", lambda: context)
    for name in ("collect_full_scope_job_summaries", "collect_full_scope_job_summaries_for_xml"):
        monkeypatch.setattr(test_report_plugin, name, lambda **kwargs: {})
    published = {}
    annotations = []

    def upload(config, generation, xml_uploads, store_context=None):
        published["summary"] = json.loads(generation.summary_path.read_text())
        html = generation.html_path.read_text()
        match = re.search(
            r'<script id="report-data" type="application/json">(.*?)</script>', html, re.DOTALL
        )
        assert match is not None
        data = json.loads(match.group(1))
        published["data"] = data[0]
        return {
            "html": PublishedObject(
                "bucket",
                "index.html",
                "https://reports.example.com/index.html" if public_url else None,
                len(html),
            )
        }

    monkeypatch.setattr(test_report_plugin, "upload_report_artifacts", upload)
    monkeypatch.setattr(
        test_report_plugin,
        "create_buildkite_annotation",
        lambda body, context, style, priority, scope: annotations.append((body, style)),
    )
    assert test_report_plugin.main() == 1
    assert published["summary"]["logical_tests"] == int(has_valid_job)
    assert published["summary"]["root_status"] == "ERRORED"
    assert len(published["summary"]["junit_archive_errors"]) == 1
    assert any(
        section["title"] == "JUnit archive errors" for section in published["data"]["sections"]
    )
    assert annotations[0][1] == "error"
    assert "junit.zip" in annotations[0][0]
    assert ("Open full report" in annotations[0][0]) == public_url
