from __future__ import annotations
from typing import List
from dataclasses import dataclass
from pathlib import Path
from plugin_config import PlatformConfig
import glob
import sys


@dataclass(frozen=True)
class XmlUpload:
    local_path: Path
    object_relative_path: str


def _collect_uploads_for_path(path: Path, prefix: str = "") -> List[XmlUpload]:
    uploads: List[XmlUpload] = []
    path_str = str(path)
    is_glob = any(c in path_str for c in "*?[]")

    if is_glob:
        cwd = Path.cwd().resolve()
        xml_files = sorted(
            {Path(f).resolve() for f in glob.glob(path_str, recursive=True) if Path(f).is_file()}
        )
        for xml_file in xml_files:
            rel_path = xml_file.relative_to(cwd).as_posix()
            object_relative_path = f"{prefix}/{rel_path}".lstrip("/") if prefix else rel_path
            uploads.append(
                XmlUpload(local_path=xml_file, object_relative_path=object_relative_path)
            )
    elif path.is_file():
        object_relative_path = f"{prefix}/{path.name}".lstrip("/") if prefix else path.name
        uploads.append(XmlUpload(local_path=path, object_relative_path=object_relative_path))
    elif path.is_dir():
        xml_files = sorted(
            (p for p in path.rglob("*.xml") if p.is_file()),
            key=lambda p: p.relative_to(path).as_posix(),
        )
        for xml_file in xml_files:
            rel_path = xml_file.relative_to(path).as_posix()
            object_relative_path = f"{prefix}/{rel_path}".lstrip("/") if prefix else rel_path
            uploads.append(
                XmlUpload(local_path=xml_file, object_relative_path=object_relative_path)
            )

    return uploads


def collect_job_xml_uploads(junit_input_path: Path, variant: str) -> List[XmlUpload]:
    """Collect job-scope JUnit XML files relative to the configured input path."""

    path_str = str(junit_input_path)
    is_glob = any(c in path_str for c in "*?[]")
    if not is_glob and not junit_input_path.exists():
        raise FileNotFoundError(
            f"junit_input_path does not exist: {junit_input_path} (variant: {variant})"
        )

    uploads = _collect_uploads_for_path(junit_input_path)
    if not uploads:
        raise FileNotFoundError(
            f"no JUnit XML files found at junit_input_path: {junit_input_path} (variant: {variant})"
        )
    return uploads


def collect_xml_uploads(platforms: List[PlatformConfig], scope: str) -> List[XmlUpload]:
    """
    Collects XML files to upload based on the provided platform configurations.
    Handles glob patterns, directories, and single files. Validates existence and raises errors or warnings based on the scope if files are missing.
    In job scope, missing files will raise FileNotFoundError. In build scope, missing files will log a warning and be skipped (later annotated as missing in the report).
    """
    uploads = []
    for platform in platforms:
        path = platform.path
        platform_uploads = []

        path_str = str(path)
        is_glob = any(c in path_str for c in "*?[]")

        if not is_glob and not path.exists():
            if scope == "job":
                raise FileNotFoundError(
                    f"platform path does not exist: {path} (platform: {platform.name})"
                )
            print(
                f"WARN  platform path does not exist: {path} (platform: {platform.name})",
                file=sys.stderr,
            )
            continue

        platform_uploads = _collect_uploads_for_path(path, platform.name)

        if not platform_uploads:
            if scope == "job":
                raise FileNotFoundError(
                    f"no JUnit XML files found for platform: {platform.name} at {path}"
                )
            print(
                f"WARN  no JUnit XML files found for platform: {platform.name} at {path}",
                file=sys.stderr,
            )
            continue

        uploads.extend(platform_uploads)

    return uploads
