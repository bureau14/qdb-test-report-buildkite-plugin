from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List
import glob
import re
import sys

from plugin_config import ArtifactConfig


@dataclass(frozen=True)
class ArtifactFile:
    config: ArtifactConfig
    local_path: Path
    relative_path: str


def warn(message: str) -> None:
    print(f"WARN  {message}", file=sys.stderr)


def slugify_artifact_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not slug:
        raise ValueError(f"artifact name does not produce a valid object slug: {name!r}")
    return slug


def has_glob_magic(path: Path) -> bool:
    return any(char in str(path) for char in "*?[]")


def _collect_for_artifact(config: ArtifactConfig) -> List[ArtifactFile]:
    input_path = config.input_path
    path_str = str(input_path)

    if has_glob_magic(input_path):
        cwd = Path.cwd().resolve()
        files = sorted(
            {
                Path(match).resolve()
                for match in glob.glob(path_str, recursive=True)
                if Path(match).is_file()
            },
            key=lambda p: p.as_posix(),
        )
        return [
            ArtifactFile(
                config=config,
                local_path=file,
                relative_path=file.relative_to(cwd).as_posix(),
            )
            for file in files
        ]

    if not input_path.exists():
        warn(f"additional artifact path does not exist: {input_path} artifact={config.name}")
        return []

    if input_path.is_file():
        return [
            ArtifactFile(
                config=config,
                local_path=input_path,
                relative_path=input_path.name,
            )
        ]

    if input_path.is_dir():
        files = sorted(
            (path for path in input_path.rglob("*") if path.is_file()),
            key=lambda p: p.relative_to(input_path).as_posix(),
        )
        return [
            ArtifactFile(
                config=config,
                local_path=file,
                relative_path=file.relative_to(input_path).as_posix(),
            )
            for file in files
        ]

    return []


def collect_artifact_files(configs: List[ArtifactConfig]) -> List[ArtifactFile]:
    seen_slugs: Dict[str, str] = {}
    for config in configs:
        slug = slugify_artifact_name(config.name)
        previous = seen_slugs.get(slug)
        if previous is not None:
            raise ValueError(
                f"duplicate artifact object slug {slug!r} for artifact names {previous!r} and {config.name!r}"
            )
        seen_slugs[slug] = config.name

    result: List[ArtifactFile] = []
    for config in configs:
        files = _collect_for_artifact(config)
        if not files:
            warn(
                f"no files found for additional artifact artifact={config.name} input_path={config.input_path}"
            )
        result.extend(files)
    return result
