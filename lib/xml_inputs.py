from __future__ import annotations
from typing import List
from dataclasses import dataclass
from pathlib import Path
from plugin_config import PlatformConfig
import sys


@dataclass(frozen=True)
class XmlUpload:
    local_path: Path
    object_relative_path: str


def collect_xml_uploads(platforms: List[PlatformConfig], scope: str) -> List[XmlUpload]:
    uploads = []
    for platform in platforms:
        path = platform.path
        if not path.exists():
            if scope == "job":
                raise FileNotFoundError(
                    f"platform path does not exist: {path} (platform: {platform.name})"
                )
            print(
                f"WARN  platform path does not exist: {path} (platform: {platform.name})",
                file=sys.stderr,
            )
            continue

        platform_uploads = []
        if path.is_file():
            # For single file, we use its name
            platform_uploads.append(
                XmlUpload(
                    local_path=path, object_relative_path=f"{platform.name}/{path.name}"
                )
            )
        elif path.is_dir():
            # For directory, we recurse and keep relative structure
            xml_files = sorted(
                (p for p in path.rglob("*.xml") if p.is_file()),
                key=lambda p: p.relative_to(path).as_posix(),
            )
            for xml_file in xml_files:
                rel_path = xml_file.relative_to(path).as_posix()
                platform_uploads.append(
                    XmlUpload(
                        local_path=xml_file,
                        object_relative_path=f"{platform.name}/{rel_path}",
                    )
                )

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
