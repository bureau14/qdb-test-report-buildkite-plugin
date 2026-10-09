import threading
import time
from pathlib import Path

import pytest
from object_store import (
    ObjectAuth,
    StoreConfig,
    UploadRequest,
    download_file,
    internal_url,
    key_join,
    list_objects,
    parse_s3,
    upload_file,
    upload_files,
)


def test_upload_batch_is_parallel_bounded_reuses_clients_and_preserves_order(monkeypatch, tmp_path):
    lock = threading.Lock()
    barrier = threading.Barrier(4)
    clients = []
    active = peak = 0

    class Client:
        def __init__(self):
            self.owner = threading.get_ident()
            self.calls = 0
            self.closed = False

        def upload_file(self, filename, bucket, key, *, ExtraArgs, Config):
            nonlocal active, peak
            assert threading.get_ident() == self.owner
            assert not Config.use_threads
            assert ExtraArgs["ContentType"] == "application/xml"
            self.calls += 1
            with lock:
                active += 1
                peak = max(peak, active)
            if self.calls == 1:
                barrier.wait(timeout=5)
            time.sleep(0.005)
            with lock:
                active -= 1

        def close(self):
            self.closed = True

    def create_client(cfg, auth):
        client = Client()
        with lock:
            clients.append(client)
        return client

    monkeypatch.setattr("object_store.create_s3_client", create_client)
    monkeypatch.setattr("object_store._with_retry", lambda fn, description: fn())
    requests = []
    for i in range(12):
        path = tmp_path / f"{i}.xml"
        path.write_text("xml")
        requests.append(UploadRequest(f"{i}.xml", path, "application/xml", "attachment"))
    results = upload_files(
        StoreConfig("s3", "s3://bucket"), ObjectAuth(), "bucket", requests, parallel=4
    )
    assert peak == 4
    assert len(clients) == 4
    assert all(client.calls > 1 and client.closed for client in clients)
    assert [result.key for result in results] == [request.key for request in requests]
    assert [result.size_bytes for result in results] == [3] * 12


def test_upload_batch_propagates_failure_and_closes_worker_clients(monkeypatch, tmp_path):
    closed = []
    error = RuntimeError("upload failed")

    class Client:
        def close(self):
            closed.append(self)

    client = Client()
    monkeypatch.setattr("object_store.create_s3_client", lambda cfg, auth: client)

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr("object_store.upload_file", fail)
    with pytest.raises(RuntimeError) as caught:
        upload_files(
            StoreConfig("s3", "s3://bucket"),
            ObjectAuth(),
            "bucket",
            [UploadRequest("test.xml", tmp_path / "test.xml", "application/xml", "attachment")],
            parallel=1,
        )
    assert caught.value is error
    assert closed == [client]


def test_upload_batch_empty_does_not_create_client(monkeypatch):
    def unexpected_client(*args):
        raise AssertionError("empty batch should not create a client")

    monkeypatch.setattr("object_store.create_s3_client", unexpected_client)
    assert upload_files(StoreConfig("s3", "s3://bucket"), ObjectAuth(), "bucket", []) == []


def test_key_join_drops_duplicate_slashes():
    assert (
        key_join("/prefix/", "/project//", "reports", "file.html")
        == "prefix/project/reports/file.html"
    )


def test_parse_s3_handles_uri_with_prefix():
    assert parse_s3("s3://bucket-name/some/prefix") == ("bucket-name", "some/prefix")


def test_parse_s3_handles_plain_bucket_name():
    assert parse_s3("bucket-name") == ("bucket-name", "")


def test_internal_url_returns_none_without_domain():
    cfg = StoreConfig(backend="s3", destination="s3://bucket/prefix")

    assert internal_url(cfg, "prefix/file.html") is None


def test_internal_url_builds_https_url_without_double_slashes():
    cfg = StoreConfig(
        backend="s3",
        destination="s3://bucket/prefix",
        artifacts_domain="reports.example.com/",
    )

    assert internal_url(cfg, "/prefix/file.html") == "https://reports.example.com/prefix/file.html"


def test_upload_file_passes_content_metadata_to_boto3(monkeypatch, tmp_path):
    uploaded = {}

    class FakeClient:
        def upload_file(self, filename, bucket, key, *, ExtraArgs, Config):
            uploaded["filename"] = filename
            uploaded["bucket"] = bucket
            uploaded["key"] = key
            uploaded["extra_args"] = ExtraArgs
            uploaded["config"] = Config

    def fake_s3_client(cfg, auth):
        return FakeClient()

    local_path = tmp_path / "index.html"
    local_path.write_text("<html></html>", encoding="utf-8")
    cfg = StoreConfig(
        backend="s3",
        destination="s3://bucket/reports",
        artifacts_domain="reports.example.com",
    )

    monkeypatch.setattr("object_store._s3_client", fake_s3_client)

    published = upload_file(
        cfg,
        ObjectAuth(),
        "bucket",
        "reports/unit/index.html",
        local_path,
        content_type="text/html; charset=utf-8",
        content_disposition="inline",
    )

    assert uploaded["filename"] == str(local_path)
    assert uploaded["bucket"] == "bucket"
    assert uploaded["key"] == "reports/unit/index.html"
    assert uploaded["extra_args"] == {
        "ContentType": "text/html; charset=utf-8",
        "ContentDisposition": "inline",
    }
    assert published.bucket == "bucket"
    assert published.key == "reports/unit/index.html"
    assert published.url == "https://reports.example.com/reports/unit/index.html"
    assert published.size_bytes == local_path.stat().st_size


def test_list_objects_reads_multiple_paginator_pages(monkeypatch):
    class FakePaginator:
        def paginate(self, *, Bucket, Prefix):
            assert Bucket == "bucket"
            assert Prefix == "prefix/reports"
            return [
                {"Contents": [{"Key": "prefix/reports/a.xml", "Size": 10}]},
                {"Contents": [{"Key": "prefix/reports/b.xml", "Size": 20}]},
                {},
            ]

    class FakeClient:
        def get_paginator(self, name):
            assert name == "list_objects_v2"
            return FakePaginator()

    monkeypatch.setattr("object_store._s3_client", lambda cfg, auth: FakeClient())

    cfg = StoreConfig(backend="s3", destination="s3://bucket/prefix")
    objects = list_objects(cfg, ObjectAuth(), "bucket", "prefix/reports")

    assert [(obj.key, obj.size_bytes) for obj in objects] == [
        ("prefix/reports/a.xml", 10),
        ("prefix/reports/b.xml", 20),
    ]


def test_download_file_creates_parent_directory_and_uses_boto3_download(monkeypatch, tmp_path):
    downloaded = {}

    class FakeClient:
        def download_file(self, bucket, key, filename, *, Config):
            downloaded["bucket"] = bucket
            downloaded["key"] = key
            downloaded["filename"] = filename
            downloaded["config"] = Config
            Path(filename).write_text("xml", encoding="utf-8")

    monkeypatch.setattr("object_store._s3_client", lambda cfg, auth: FakeClient())

    cfg = StoreConfig(backend="s3", destination="s3://bucket/prefix")
    local_path = tmp_path / "nested" / "report.xml"

    download_file(cfg, ObjectAuth(), "bucket", "prefix/report.xml", local_path, concurrency=7)

    assert local_path.read_text(encoding="utf-8") == "xml"
    assert downloaded["bucket"] == "bucket"
    assert downloaded["key"] == "prefix/report.xml"
    assert downloaded["filename"] == str(local_path)
    assert downloaded["config"] is not None
