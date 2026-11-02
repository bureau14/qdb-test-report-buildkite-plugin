import io
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from ctest_cost_data import (
    MAX_COST_BYTES,
    MAX_DISCOVERY_OBJECTS,
    list_descriptor_candidates,
    main,
    read_object,
    restore_cost_data,
    sanitize_cost_data,
)
from object_store import ObjectAuth, StoreConfig
from plugin_config import CTestCostDataRestoreConfig, PluginConfig
from report_paths import build_ctest_cost_data_descriptor_key, build_report_location
from test_report_plugin import ObjectStoreContext

RAW_COSTS = b"test with spaces 3 2.5\r\nsecond 1 0\r\n---\r\nfailed-before\r\n"
SANITIZED = b"test with spaces 3 2.5\nsecond 1 0\n---\n"


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.setenv("BUILDKITE_BUILD_NUMBER", "100")
    monkeypatch.setenv("BUILDKITE_STEP_KEY", "test/parallel")
    return PluginConfig(
        scope="job",
        title="Report",
        variant="linux-arm64-debug",
        execution_name=None,
        project_id="project",
        git_ref="refs/heads/feature/costs",
        build_id="current-build",
        job_id="current-job",
        build_url=None,
        platforms=[],
        only_failures=False,
        annotate=False,
        fail_on_test_failures=False,
        ctest_cost_data_path=tmp_path / "build/Testing/Temporary/CTestCostData.txt",
        ctest_cost_data_selection=["bk-suite:unit"],
        ctest_cost_data_restore=CTestCostDataRestoreConfig(tmp_path / "staging/costs.txt"),
    )


class Storage:
    def __init__(self):
        self.objects = {}
        self.requests = []
        self.prefixes = []
        self.closed = False

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, *, Bucket, Prefix, PaginationConfig):
        self.prefixes.append(Prefix)
        yield {
            "Contents": [
                {"Key": key, "Size": len(data)}
                for key, data in self.objects.items()
                if key.startswith(Prefix)
            ]
        }

    def get_object(self, *, Bucket, Key):
        self.requests.append(Key)
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        data = self.objects[Key]
        return {"ContentLength": len(data), "Body": io.BytesIO(data)}

    def close(self):
        self.closed = True


@pytest.fixture
def storage(monkeypatch):
    client = Storage()
    context = ObjectStoreContext(
        StoreConfig("s3", "s3://bucket/prefix"), ObjectAuth(), "bucket", "prefix"
    )
    monkeypatch.setattr("ctest_cost_data.resolve_object_store_context", lambda: context)
    monkeypatch.setattr("ctest_cost_data.create_s3_client", lambda cfg, auth: client)
    return client


def archive(storage, config, number=99, job="job", retry=0, raw=RAW_COSTS, **overrides):
    metadata = {
        "version": 1,
        "project_id": config.project_id,
        "git_ref": config.git_ref,
        "variant": config.variant,
        "step_key": "test/parallel",
        "selection": ["bk-suite:unit"],
        "build_number": number,
        "build_id": "build-" + str(number),
        "job_id": job,
        "retry_count": retry,
        "command_exit_status": 0,
        "status_counts": {"SUCCESSFUL": 2},
        "size_bytes": len(raw),
    }
    metadata.update(overrides)
    location = build_report_location(
        destination_prefix="prefix",
        project_id=metadata["project_id"],
        git_ref=metadata["git_ref"],
        build_id=metadata["build_id"],
        scope="job",
        variant=metadata["variant"],
        job_id=metadata["job_id"],
    )
    metadata["key"] = location.base_prefix + "/CTestCostData.txt"
    metadata["summary_key"] = location.summary_key
    key = build_ctest_cost_data_descriptor_key(
        destination_prefix="prefix",
        project_id=metadata["project_id"],
        git_ref=metadata["git_ref"],
        variant=metadata["variant"],
        step_key=metadata["step_key"],
        build_number=number,
        job_id=job,
    )
    storage.objects[key] = json.dumps(metadata).encode()
    storage.objects[metadata["key"]] = raw
    return key, metadata


def test_prefers_branch_and_numeric_build_and_latest_retry(config, storage, tmp_path):
    archive(storage, config, number=9, job="old")
    archive(storage, config, number=99, job="z-first", retry=0)
    _, newest = archive(storage, config, number=99, job="a-retry", retry=2)
    archive(storage, config, number=100, job="current")
    archive(storage, config, number=101, job="future")
    archive(storage, config, number=99, job="master", git_ref="refs/heads/master")
    output = tmp_path / "output"
    assert restore_cost_data(config, output)
    assert output.read_bytes() == SANITIZED
    assert storage.requests[-1] == newest["key"]
    assert len(storage.prefixes) == 1
    assert storage.objects[newest["key"]] == RAW_COSTS
    assert storage.closed


@pytest.mark.parametrize(
    "overrides",
    [
        {"selection": None},
        {"selection": ["bk-suite:regression"]},
        {"command_exit_status": None},
        {"command_exit_status": 1},
        {"command_exit_status": False},
        {"status_counts": {}},
        {"status_counts": {"FAILED": 1, "SUCCESSFUL": 2}},
        {"status_counts": {"ERRORED": 1, "SUCCESSFUL": 2}},
        {"status_counts": {"SUCCESSFUL": True}},
        {"status_counts": {"SUCCESSFUL": -1}},
        {"status_counts": {"SUCCESSFUL": 1, "UNKNOWN": 1}},
        {"build_id": "current-build"},
        {"version": 2},
        {"version": True},
        {"retry_count": -1},
        {"size_bytes": MAX_COST_BYTES + 1},
        {"project_id": "other"},
        {"variant": "linux-x64-debug"},
        {"step_key": "test"},
    ],
)
def test_ineligible_branch_snapshot_falls_back(config, storage, tmp_path, overrides):
    archive(storage, config, **overrides)
    _, fallback = archive(storage, config, number=98, job="master", git_ref="refs/heads/master")
    output = tmp_path / "output"
    assert restore_cost_data(config, output)
    assert storage.requests[-1] == fallback["key"]
    assert output.read_bytes() == SANITIZED


@pytest.mark.parametrize(
    "damage", ["missing", "malformed", "wrong-size", "wrong-reference", "bad-json"]
)
def test_bad_snapshot_tries_older_build(config, storage, tmp_path, damage):
    descriptor, newest = archive(storage, config)
    _, older = archive(storage, config, number=98, job="older")
    if damage == "missing":
        del storage.objects[newest["key"]]
    elif damage == "malformed":
        storage.objects[newest["key"]] = b"broken"
        newest["size_bytes"] = 6
    elif damage == "wrong-size":
        newest["size_bytes"] += 1
    elif damage == "wrong-reference":
        newest["key"] = "outside-project/costs"
    if damage == "bad-json":
        storage.objects[descriptor] = b"{"
    else:
        storage.objects[descriptor] = json.dumps(newest).encode()
    assert restore_cost_data(config, tmp_path / "output")
    assert storage.requests[-1] == older["key"]


@pytest.mark.parametrize("selection", [[], ["another-suite"]])
def test_unknown_or_unmatched_selection_is_cold(config, storage, tmp_path, selection):
    archive(storage, config)
    output = tmp_path / "output"
    assert not restore_cost_data(replace(config, ctest_cost_data_selection=selection), output)
    assert not output.exists()


def test_disabled_fallback_and_same_branch_are_not_searched_twice(config, storage, tmp_path):
    for fallback in (None, "feature/costs"):
        storage.prefixes.clear()
        restore = replace(config.ctest_cost_data_restore, fallback_branch=fallback)
        assert not restore_cost_data(
            replace(config, ctest_cost_data_restore=restore), tmp_path / "output"
        )
        assert len(storage.prefixes) == 1


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"---\n",
        b"test 1 2\n",
        b"test -1 2\n---\n",
        b"test 1 nan\n---\n",
        b"test 1 inf\n---\n",
        b"test 1 -1\n---\n",
        b"test nope 2\n---\n",
        b"\xff\n---\n",
    ],
)
def test_rejects_malformed_cost_data(raw):
    with pytest.raises(ValueError):
        sanitize_cost_data(raw)


def test_discovery_stops_at_object_limit():
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [
        {
            "Contents": [{"Key": "prefix/99/job.json", "Size": 1}] * MAX_DISCOVERY_OBJECTS,
            "IsTruncated": True,
        }
    ]
    with pytest.raises(ValueError, match="object limit"):
        list_descriptor_candidates(client, "bucket", "prefix/", 100)


def test_read_limit_closes_body():
    client = MagicMock()
    body = io.BytesIO(b"too large")
    client.get_object.return_value = {"Body": body, "ContentLength": 9}
    with pytest.raises(ValueError, match="size limit"):
        read_object(client, "bucket", "key", 4)
    assert body.closed


@pytest.mark.parametrize("result", ["success", "cold", "timeout", "failure"])
def test_main_clears_stale_staging_and_installs_atomically(config, monkeypatch, result):
    staging = config.ctest_cost_data_restore.staging_path
    staging.parent.mkdir()
    staging.write_text("stale")
    monkeypatch.setattr("ctest_cost_data.load_plugin_config", lambda: config)

    def run(args, *, timeout, check):
        assert timeout == 30 and check
        assert not staging.exists()
        assert args[-2] == "--worker"
        if result == "timeout":
            Path(args[-1]).write_text("unfinished")
            raise subprocess.TimeoutExpired(args, timeout)
        if result == "failure":
            raise subprocess.CalledProcessError(1, args)
        if result == "success":
            Path(args[-1]).write_bytes(SANITIZED)

    monkeypatch.setattr("ctest_cost_data.subprocess.run", run)
    assert main([]) == 0
    assert staging.exists() == (result == "success")
    if staging.exists():
        assert staging.read_bytes() == SANITIZED
    assert list(staging.parent.iterdir()) == ([staging] if staging.exists() else [])


def test_main_worker_uses_same_selection(config, storage, monkeypatch, tmp_path):
    archive(storage, config)
    monkeypatch.setattr("ctest_cost_data.load_plugin_config", lambda: config)
    output = tmp_path / "worker-output"
    assert main(["--worker", str(output)]) == 0
    assert output.read_bytes() == SANITIZED


def test_main_disabled_does_not_touch_files(config, monkeypatch):
    monkeypatch.setattr(
        "ctest_cost_data.load_plugin_config", lambda: replace(config, ctest_cost_data_restore=None)
    )
    run = MagicMock()
    monkeypatch.setattr("ctest_cost_data.subprocess.run", run)
    assert main([]) == 0
    run.assert_not_called()


def test_main_rejects_archive_as_staging(config, monkeypatch):
    archive_path = config.ctest_cost_data_path
    archive_path.parent.mkdir(parents=True)
    archive_path.write_text("original")
    config = replace(config, ctest_cost_data_restore=CTestCostDataRestoreConfig(archive_path))
    monkeypatch.setattr("ctest_cost_data.load_plugin_config", lambda: config)
    assert main([]) == 0
    assert archive_path.read_text() == "original"


def test_real_worker_timeout_does_not_install_partial_output(config, monkeypatch, tmp_path):
    worker = tmp_path / "slow_worker.py"
    worker.write_text(
        "import sys, time\nfrom pathlib import Path\n"
        "Path(sys.argv[-1]).write_text('partial')\ntime.sleep(60)\n"
    )
    restore = replace(config.ctest_cost_data_restore, timeout_seconds=1)
    config = replace(config, ctest_cost_data_restore=restore)
    monkeypatch.setattr("ctest_cost_data.load_plugin_config", lambda: config)
    monkeypatch.setattr("ctest_cost_data.__file__", str(worker))
    assert main([]) == 0
    assert not restore.staging_path.exists()
    assert not list(restore.staging_path.parent.iterdir())


def test_discovery_failure_can_use_fallback(config, storage, monkeypatch, tmp_path):
    _, fallback = archive(storage, config, git_ref="refs/heads/master")
    paginate = storage.paginate

    def fail_current_branch(**kwargs):
        if "/refs/heads/feature/costs/" in kwargs["Prefix"]:
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "ListObjectsV2")
        return paginate(**kwargs)

    monkeypatch.setattr(storage, "paginate", fail_current_branch)
    assert restore_cost_data(config, tmp_path / "output")
    assert storage.requests[-1] == fallback["key"]


def test_newest_candidate_limit_is_numeric(monkeypatch):
    client = Storage()
    for number in range(1, 100):
        client.objects["prefix/" + str(number) + "/job.json"] = b"{}"
    monkeypatch.setattr("ctest_cost_data.MAX_DESCRIPTORS", 3)
    assert [
        number for number, key in list_descriptor_candidates(client, "bucket", "prefix/", 100)
    ] == [99, 98, 97]


def test_worker_write_failure_cannot_publish_partial_output(config, monkeypatch, tmp_path):
    output = tmp_path / "partial"
    monkeypatch.setattr("ctest_cost_data.load_plugin_config", lambda: config)

    def fail_write(config, path):
        path.write_text("partial")
        raise OSError("disk full")

    monkeypatch.setattr("ctest_cost_data.restore_cost_data", fail_write)
    assert main(["--worker", str(output)]) == 1


def test_missing_step_key_does_not_resolve_credentials(config, monkeypatch, tmp_path):
    monkeypatch.delenv("BUILDKITE_STEP_KEY", raising=False)
    setup = MagicMock()
    monkeypatch.setattr("ctest_cost_data.resolve_object_store_context", setup)
    assert not restore_cost_data(config, tmp_path / "output")
    setup.assert_not_called()
