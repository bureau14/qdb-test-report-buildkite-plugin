import threading
import time
from zipfile import ZipFile, ZipInfo

import pytest
from object_store import ObjectAuth, StoreConfig
from report_downloads import (
    JobXmlObject,
    build_aggregate_xml_discovery_prefix,
    collect_full_scope_xml,
    find_job_xml_objects,
)


class FakeObject:
    def __init__(self, key, size=1):
        self.key = key
        self.size_bytes = size


def test_discovery_prefers_archive_for_job_but_retains_legacy_jobs(monkeypatch):
    def objects(cfg, auth, bucket, prefix):
        return [
            FakeObject(prefix + suffix)
            for suffix in (
                "/linux/jobs/job-1/xml/old.xml",
                "/linux/jobs/job-1/xml/junit.zip",
                "/linux/jobs/job-2/xml/legacy.xml",
            )
        ]

    monkeypatch.setattr("report_downloads.list_objects", objects)
    found = find_job_xml_objects(
        cfg=StoreConfig("s3", "s3://bucket"),
        auth=ObjectAuth(),
        bucket="bucket",
        destination_prefix="",
        project_id="p",
        git_ref="main",
        build_id="b",
    )
    assert [(obj.job_id, obj.relative_path) for obj in found] == [
        ("job-1", "junit.zip"),
        ("job-2", "legacy.xml"),
    ]


@pytest.mark.parametrize(
    "member", ["nested/results.xml", "../escape.xml", "C:/escape.xml", "nested\\escape.xml"]
)
def test_collect_archive_preserves_member_identity_and_rejects_unsafe_paths(
    monkeypatch, tmp_path, member
):
    obj = JobXmlObject("linux", "job-1", "prefix/linux/jobs/job-1/xml/junit.zip", "junit.zip", 10)
    monkeypatch.setattr("report_downloads.find_job_xml_objects", lambda **kwargs: [obj])
    monkeypatch.setattr("report_downloads.create_s3_client", lambda *args: object())

    def download(cfg, auth, bucket, key, local_path, **kwargs):
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(local_path, "w") as archive:
            info = ZipInfo(member)
            # ZipInfo normalizes Windows separators; construct an actual unsafe ZIP entry.
            info.filename = member
            archive.writestr(info, "<testsuites />")

    monkeypatch.setattr("report_downloads.download_file", download)
    kwargs = {
        "cfg": StoreConfig("s3", "s3://bucket"),
        "auth": ObjectAuth(),
        "bucket": "bucket",
        "destination_prefix": "",
        "project_id": "p",
        "git_ref": "main",
        "build_id": "b",
        "output_dir": tmp_path,
    }
    if member != "nested/results.xml":
        errors = []
        assert collect_full_scope_xml(**kwargs, archive_errors=errors) == []
        assert len(errors) == 1
        assert "Unsafe" in errors[0]["error"]
        assert list(tmp_path.rglob("*.xml")) == []
        return
    result = collect_full_scope_xml(**kwargs)
    assert len(result) == 1
    assert result[0].object.key == obj.key
    assert result[0].object.archive_member == member
    assert result[0].object_relative_path == "linux/job-1/nested/results.xml"
    assert result[0].local_path.read_text() == "<testsuites />"
    assert not (tmp_path / "linux/job-1/.junit.zip").exists()


def test_build_aggregate_xml_discovery_prefix_matches_build_layout():
    assert (
        build_aggregate_xml_discovery_prefix(
            destination_prefix="prefix",
            project_id="project",
            git_ref="refs/heads/main",
            build_id="build-1",
        )
        == "prefix/project/refs/heads/main/reports/builds/build-1/variants"
    )


def test_find_job_xml_objects_discovers_variants_and_jobs_from_build_prefix(
    monkeypatch,
):
    calls = []

    def fake_list_objects(cfg, auth, bucket, prefix):
        calls.append((bucket, prefix))
        return [
            FakeObject(prefix + "/linux/jobs/job-1/xml/results/unit.xml", 10),
            FakeObject(prefix + "/linux/jobs/job-1/index.html", 20),
            FakeObject(prefix + "/macos/jobs/job-2/xml/nested/integration.xml", 30),
            FakeObject(prefix + "/macos/jobs/job-2/xml/notes.txt", 40),
        ]

    monkeypatch.setattr("report_downloads.list_objects", fake_list_objects)

    cfg = StoreConfig(backend="s3", destination="s3://bucket/prefix")
    found = find_job_xml_objects(
        cfg=cfg,
        auth=ObjectAuth(),
        bucket="bucket",
        destination_prefix="prefix",
        project_id="project",
        git_ref="refs/heads/main",
        build_id="build-1",
    )

    assert calls == [
        (
            "bucket",
            "prefix/project/refs/heads/main/reports/builds/build-1/variants",
        )
    ]
    assert [(item.variant, item.job_id, item.relative_path, item.size_bytes) for item in found] == [
        ("linux", "job-1", "results/unit.xml", 10),
        ("macos", "job-2", "nested/integration.xml", 30),
    ]


def test_collect_full_scope_xml_downloads_to_variant_job_directories(monkeypatch, tmp_path):
    downloaded = []

    objects = [
        JobXmlObject(
            variant="linux",
            job_id="job-1",
            key="prefix/project/refs/heads/main/reports/builds/build-1/variants/linux/jobs/job-1/xml/results/unit.xml",
            relative_path="results/unit.xml",
            size_bytes=10,
        )
    ]

    monkeypatch.setattr("report_downloads.find_job_xml_objects", lambda **kwargs: objects)

    def fake_download_file(cfg, auth, bucket, key, local_path, **kwargs):
        downloaded.append((bucket, key, local_path, kwargs["concurrency"], kwargs["client"]))
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text("<testsuites />", encoding="utf-8")

    client = object()
    monkeypatch.setattr("report_downloads.create_s3_client", lambda cfg, auth: client)
    monkeypatch.setattr("report_downloads.download_file", fake_download_file)

    cfg = StoreConfig(backend="s3", destination="s3://bucket/prefix")
    result = collect_full_scope_xml(
        cfg=cfg,
        auth=ObjectAuth(),
        bucket="bucket",
        destination_prefix="prefix",
        project_id="project",
        git_ref="refs/heads/main",
        build_id="build-1",
        output_dir=tmp_path,
        download_parallel=4,
        download_concurrency=2,
    )

    expected_path = tmp_path / "linux" / "job-1" / "results" / "unit.xml"
    assert downloaded == [("bucket", objects[0].key, expected_path, 2, client)]
    assert result[0].local_path == expected_path
    assert result[0].object_relative_path == "linux/job-1/results/unit.xml"
    assert expected_path.read_text(encoding="utf-8") == "<testsuites />"


def test_collect_full_scope_xml_returns_empty_when_no_xml(monkeypatch, tmp_path):
    monkeypatch.setattr("report_downloads.find_job_xml_objects", lambda **kwargs: [])

    cfg = StoreConfig(backend="s3", destination="s3://bucket/prefix")
    result = collect_full_scope_xml(
        cfg=cfg,
        auth=ObjectAuth(),
        bucket="bucket",
        destination_prefix="prefix",
        project_id="project",
        git_ref="refs/heads/main",
        build_id="build-1",
        output_dir=tmp_path,
    )
    assert result == []


def test_collect_full_scope_xml_downloads_in_parallel_with_trace_logs(monkeypatch, tmp_path):
    objects = [
        JobXmlObject(
            variant="linux",
            job_id=f"job-{idx}",
            key=f"prefix/project/refs/heads/main/reports/builds/build-1/variants/linux/jobs/job-{idx}/xml/result.xml",
            relative_path="result.xml",
            size_bytes=1024,
        )
        for idx in range(6)
    ]

    monkeypatch.setattr("report_downloads.find_job_xml_objects", lambda **kwargs: objects)

    clients = []
    client_lock = threading.Lock()

    def fake_create_s3_client(cfg, auth):
        client = object()
        with client_lock:
            clients.append(client)
        return client

    monkeypatch.setattr("report_downloads.create_s3_client", fake_create_s3_client)

    active = 0
    max_active = 0
    active_lock = threading.Lock()

    def fake_download_file(cfg, auth, bucket, key, local_path, **kwargs):
        nonlocal active, max_active
        assert kwargs["concurrency"] == 3
        assert kwargs["client"] is not None
        with active_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.02)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text("<testsuites />", encoding="utf-8")
        with active_lock:
            active -= 1

    monkeypatch.setattr("report_downloads.download_file", fake_download_file)

    logs = []
    cfg = StoreConfig(backend="s3", destination="s3://bucket/prefix")
    result = collect_full_scope_xml(
        cfg=cfg,
        auth=ObjectAuth(),
        bucket="bucket",
        destination_prefix="prefix",
        project_id="project",
        git_ref="refs/heads/main",
        build_id="build-1",
        output_dir=tmp_path,
        download_parallel=3,
        download_concurrency=3,
        log_fn=logs.append,
    )

    assert [item.object for item in result] == objects
    assert max_active > 1
    assert 1 <= len(clients) <= 3
    assert any("Listed aggregate JUnit XML objects: 6 XML files" in msg for msg in logs)
    assert any("parallel=3, concurrency=3" in msg for msg in logs)
    assert any("Downloaded aggregate JUnit XML objects: 6 files" in msg for msg in logs)


@pytest.mark.parametrize("mode", ["direct", "fallback"])
def test_job_summary_downloads_overlap_deduplicate_and_preserve_order(tmp_path, monkeypatch, mode):
    import json
    from collections import Counter
    from unittest.mock import MagicMock

    from report_downloads import (
        DownloadedJobXml,
        JobSummaryObject,
        collect_full_scope_job_summaries,
        collect_full_scope_job_summaries_for_xml,
    )

    barrier = threading.Barrier(2)
    clients = []
    keys = []
    lock = threading.Lock()

    def create_client(cfg, auth):
        client = MagicMock()
        client.owner = threading.get_ident()
        with lock:
            clients.append(client)
        return client

    def download(cfg, auth, bucket, key, local_path, *, client, transfer_config):
        assert client.owner == threading.get_ident()
        assert transfer_config.use_threads is False
        with lock:
            keys.append(key)
        barrier.wait(timeout=5)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(json.dumps({"source": key}), encoding="utf-8")

    monkeypatch.setattr("report_downloads.create_s3_client", create_client)
    monkeypatch.setattr("report_downloads.download_file", download)
    xml = [
        DownloadedJobXml(
            JobXmlObject("linux", f"job-{i}", f"p/linux/jobs/job-{i}/xml/{j}.xml", f"{j}.xml", 1),
            tmp_path / f"{i}-{j}.xml",
        )
        for i in range(4)
        for j in range(2)
    ]
    if mode == "direct":
        summaries = collect_full_scope_job_summaries_for_xml(
            cfg=StoreConfig("s3", "s3://bucket"),
            auth=ObjectAuth(),
            bucket="bucket",
            downloaded_xml=xml,
            output_dir=tmp_path / "summaries",
            download_parallel=2,
        )
    else:
        objects = [
            JobSummaryObject("linux", f"job-{i}", f"p/linux/jobs/job-{i}/summary.json", 1)
            for i in range(4)
        ]
        monkeypatch.setattr("report_downloads.find_job_summary_objects", lambda **kwargs: objects)
        summaries = collect_full_scope_job_summaries(
            cfg=StoreConfig("s3", "s3://bucket"),
            auth=ObjectAuth(),
            bucket="bucket",
            destination_prefix="",
            project_id="p",
            git_ref="main",
            build_id="b",
            output_dir=tmp_path / "summaries",
            download_parallel=2,
        )
    assert list(summaries) == [f"job-{i}" for i in range(4)]
    assert Counter(keys) == Counter(f"p/linux/jobs/job-{i}/summary.json" for i in range(4))
    assert len(clients) == 2
    for client in clients:
        client.close.assert_called_once()
    assert summaries["job-0"]["variant"] == "linux"
    assert summaries["job-0"]["source"] == "p/linux/jobs/job-0/summary.json"


def test_job_summary_downloads_keep_missing_and_invalid_sidecars_optional(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from report_downloads import DownloadedJobXml, collect_full_scope_job_summaries_for_xml

    clients = []

    def create_client(cfg, auth):
        client = MagicMock()
        clients.append(client)
        return client

    def download(cfg, auth, bucket, key, local_path, **kwargs):
        if "/job-1/" in key:
            raise OSError("missing sidecar")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text("{" if "/job-2/" in key else "{}", encoding="utf-8")

    monkeypatch.setattr("report_downloads.create_s3_client", create_client)
    monkeypatch.setattr("report_downloads.download_file", download)
    xml = [
        DownloadedJobXml(
            JobXmlObject(
                "linux", f"job-{i}", f"p/linux/jobs/job-{i}/xml/junit.zip", "junit.zip", 1
            ),
            tmp_path / f"{i}.xml",
        )
        for i in range(4)
    ]
    summaries = collect_full_scope_job_summaries_for_xml(
        cfg=StoreConfig("s3", "s3://bucket"),
        auth=ObjectAuth(),
        bucket="bucket",
        downloaded_xml=xml,
        output_dir=tmp_path / "summaries",
        download_parallel=2,
    )
    assert list(summaries) == ["job-0", "job-3"]
    for client in clients:
        client.close.assert_called_once()


def test_fallback_summary_transport_failure_propagates_and_closes_clients(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from report_downloads import JobSummaryObject, collect_full_scope_job_summaries

    client = MagicMock()
    monkeypatch.setattr("report_downloads.create_s3_client", lambda cfg, auth: client)
    monkeypatch.setattr(
        "report_downloads.find_job_summary_objects",
        lambda **kwargs: [JobSummaryObject("linux", "job", "summary.json", 1)],
    )

    def fail_download(*args, **kwargs):
        raise OSError("download failed")

    monkeypatch.setattr("report_downloads.download_file", fail_download)
    with pytest.raises(OSError, match="download failed"):
        collect_full_scope_job_summaries(
            cfg=StoreConfig("s3", "s3://bucket"),
            auth=ObjectAuth(),
            bucket="bucket",
            destination_prefix="",
            project_id="p",
            git_ref="main",
            build_id="b",
            output_dir=tmp_path,
            download_parallel=2,
        )
    client.close.assert_called_once()
