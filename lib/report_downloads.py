from __future__ import annotations
from typing import List, Optional

from dataclasses import dataclass, replace
from pathlib import Path
from object_store import ObjectAuth, StoreConfig, download_file, key_join, list_objects
import sys


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


def build_job_xml_prefix(
    *,
    destination_prefix: str,
    project_id: str,
    git_ref: str,
    build_id: str,
    variant: str,
) -> str:
    """Return the job-scope report prefix that contains per-job XML directories."""

    return key_join(
        destination_prefix,
        project_id,
        git_ref,
        "reports",
        "variants",
        variant,
        "builds",
        build_id,
        "jobs",
    )


def attempted_job_xml_prefixes(
    *,
    bucket: str,
    destination_prefix: str,
    project_id: str,
    git_ref: str,
    build_id: str,
    variants: List[str],
) -> List[str]:
    return [
        f"s3://{bucket}/{build_job_xml_prefix(destination_prefix=destination_prefix, project_id=project_id, git_ref=git_ref, build_id=build_id, variant=variant)}"
        for variant in variants
    ]


def _xml_metadata_from_key(*, variant: str, prefix: str, key: str, size_bytes: int) -> Optional[JobXmlObject]:
    if not key.endswith(".xml"):
        return None
    relative_to_jobs = key[len(prefix) :].lstrip("/") if key.startswith(prefix) else key
    parts = relative_to_jobs.split("/", 2)
    if len(parts) != 3:
        return None
    job_id, marker, relative_path = parts
    if marker != "xml" or not job_id or not relative_path:
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
    variants: List[str],
) -> List[JobXmlObject]:
    """Find JUnit XML objects uploaded by job-scope report steps."""

    found: List[JobXmlObject] = []
    for variant in variants:
        prefix = build_job_xml_prefix(
            destination_prefix=destination_prefix,
            project_id=project_id,
            git_ref=git_ref,
            build_id=build_id,
            variant=variant,
        )
        for obj in list_objects(cfg, auth, bucket, prefix):
            metadata = _xml_metadata_from_key(
                variant=variant,
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
    variants: List[str],
    output_dir: Path,
) -> List[DownloadedJobXml]:
    """Download job-scope XML into a full-scope staging directory."""

    objects = find_job_xml_objects(
        cfg=cfg,
        auth=auth,
        bucket=bucket,
        destination_prefix=destination_prefix,
        project_id=project_id,
        git_ref=git_ref,
        build_id=build_id,
        variants=variants,
    )
    # if no files found, raise an error with the attempted prefixes for easier debugging of misconfigurations or missing uploads
    if not objects:
        prefixes = attempted_job_xml_prefixes(
            bucket=bucket,
            destination_prefix=destination_prefix,
            project_id=project_id,
            git_ref=git_ref,
            build_id=build_id,
            variants=variants,
        )
        details = "\n".join(f"  - {prefix}" for prefix in prefixes)
        print(f"WARN  no JUnit XML objects found for full-scope aggregation. Attempted prefixes:\n{details}", file=sys.stderr)
        return []

    downloaded: List[DownloadedJobXml] = []
    for obj in objects:
        local_path = Path(output_dir) / obj.variant / obj.job_id / obj.relative_path
        download_file(cfg, auth, bucket, obj.key, local_path)
        downloaded.append(DownloadedJobXml(object=obj, local_path=local_path))
    return downloaded
