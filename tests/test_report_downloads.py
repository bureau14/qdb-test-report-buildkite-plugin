import threading
import time

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
