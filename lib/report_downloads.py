from __future__ import annotations
from typing import Callable, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time

from dataclasses import dataclass
from pathlib import Path
from boto3.s3.transfer import TransferConfig
from object_store import (
    ObjectAuth,
    StoreConfig,
    create_s3_client,
    download_file,
    key_join,
    list_objects,
)


@dataclass(frozen=True)
class JobXmlObject:
    variant: str
    job_id: str
    key: str
    relative_path: str
    size_bytes: int

    @property
    def object_relative_path(self) -> str:
        return key_join(self.variant, self.job_id, self.relative_path)


@dataclass(frozen=True)
class DownloadedJobXml:
    object: JobXmlObject
    local_path: Path

    @property
    def variant(self) -> str:
        return self.object.variant

    @property
    def job_id(self) -> str:
        return self.object.job_id

    @property
    def relative_path(self) -> str:
        return self.object.relative_path

    @property
    def object_relative_path(self) -> str:
        return self.object.object_relative_path


def _fmt_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size_bytes} B"


def build_aggregate_xml_discovery_prefix(
    *,
    destination_prefix: str,
    project_id: str,
    git_ref: str,
    build_id: str,
) -> str:
    """Return the build-level prefix that contains all variant/job XML uploads."""

    return key_join(
        destination_prefix,
        project_id,
        git_ref,
        "reports",
        "builds",
        build_id,
        "variants",
    )


def _xml_metadata_from_key(*, prefix: str, key: str, size_bytes: int) -> Optional[JobXmlObject]:
    if not key.endswith(".xml"):
        return None
    relative_to_variants = key[len(prefix) :].lstrip("/") if key.startswith(prefix) else key
    parts = relative_to_variants.split("/", 4)
    if len(parts) != 5:
        return None
    variant, jobs_marker, job_id, xml_marker, relative_path = parts
    if jobs_marker != "jobs" or xml_marker != "xml":
        return None
    if not variant or not job_id or not relative_path:
        return None
    return JobXmlObject(
        variant=variant,
        job_id=job_id,
        key=key,
        relative_path=relative_path,
        size_bytes=size_bytes,
    )


def find_job_xml_objects(
    *,
    cfg: StoreConfig,
    auth: ObjectAuth,
    bucket: str,
    destination_prefix: str,
    project_id: str,
    git_ref: str,
    build_id: str,
) -> List[JobXmlObject]:
    """Find JUnit XML objects uploaded by job-scope report steps for a build."""

    prefix = build_aggregate_xml_discovery_prefix(
        destination_prefix=destination_prefix,
        project_id=project_id,
        git_ref=git_ref,
        build_id=build_id,
    )
    found: List[JobXmlObject] = []
    for obj in list_objects(cfg, auth, bucket, prefix):
        metadata = _xml_metadata_from_key(
            prefix=prefix,
            key=obj.key,
            size_bytes=obj.size_bytes,
        )
        if metadata is not None:
            found.append(metadata)
    return found


def collect_full_scope_xml(
    *,
    cfg: StoreConfig,
    auth: ObjectAuth,
    bucket: str,
    destination_prefix: str,
    project_id: str,
    git_ref: str,
    build_id: str,
    output_dir: Path,
    download_parallel: int = 32,
    download_concurrency: int = 4,
    log_fn: Optional[Callable[[str], None]] = None,
) -> List[DownloadedJobXml]:
    """Download discovered job-scope XML into a full-scope staging directory."""

    list_started = time.monotonic()
    objects = find_job_xml_objects(
        cfg=cfg,
        auth=auth,
        bucket=bucket,
        destination_prefix=destination_prefix,
        project_id=project_id,
        git_ref=git_ref,
        build_id=build_id,
    )
    list_elapsed = time.monotonic() - list_started
    total_bytes = sum(obj.size_bytes for obj in objects)
    if log_fn:
        log_fn(
            "Listed aggregate JUnit XML objects: "
            f"{len(objects)} XML files ({_fmt_size(total_bytes)}) in {list_elapsed:.1f}s."
        )

    if not objects:
        return []

    workers = max(1, min(download_parallel, len(objects)))
    transfer_config = TransferConfig(max_concurrency=download_concurrency)
    thread_state = threading.local()

    if log_fn:
        log_fn(
            "Downloading aggregate JUnit XML objects: "
            f"parallel={workers}, concurrency={download_concurrency}."
        )

    def _thread_client():
        client = getattr(thread_state, "client", None)
        if client is None:
            client = create_s3_client(cfg, auth)
            thread_state.client = client
        return client

    def _download_one(obj: JobXmlObject) -> DownloadedJobXml:
        local_path = Path(output_dir) / obj.variant / obj.job_id / obj.relative_path
        download_file(
            cfg,
            auth,
            bucket,
            obj.key,
            local_path,
            concurrency=download_concurrency,
            client=_thread_client(),
            transfer_config=transfer_config,
        )
        return DownloadedJobXml(object=obj, local_path=local_path)

    downloaded: List[Optional[DownloadedJobXml]] = [None] * len(objects)
    download_started = time.monotonic()
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_download_one, obj): idx for idx, obj in enumerate(objects)}
        for future in as_completed(futures):
            idx = futures[future]
            downloaded[idx] = future.result()
            completed += 1
            if log_fn and completed < len(objects) and completed % 100 == 0:
                elapsed = time.monotonic() - download_started
                log_fn(
                    "Downloaded aggregate JUnit XML progress: "
                    f"{completed}/{len(objects)} files in {elapsed:.1f}s."
                )

    download_elapsed = time.monotonic() - download_started
    throughput = total_bytes / download_elapsed if download_elapsed > 0 else 0
    if log_fn:
        log_fn(
            "Downloaded aggregate JUnit XML objects: "
            f"{len(objects)} files ({_fmt_size(total_bytes)}) in {download_elapsed:.1f}s "
            f"({_fmt_size(int(throughput))}/s)."
        )
    return [item for item in downloaded if item is not None]
