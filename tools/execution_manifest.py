"""Versioned execution metadata, independent of JUnit and artifact naming."""

from __future__ import annotations

import glob
import json
from pathlib import Path, PurePosixPath

import fastjsonschema

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas/execution-manifest-v1.schema.json"
VALIDATOR = fastjsonschema.compile(
    json.loads(SCHEMA_PATH.read_text(encoding="utf-8")), use_default=False
)


def validate_manifest(data: dict) -> dict:
    VALIDATOR(data)
    paths = [item["path"] for item in data["artifacts"]]
    if len(paths) != len(set(paths)):
        raise ValueError("execution manifest contains duplicate artifact paths")
    return data


def local_path(root: Path, relative: str) -> Path:
    # Resolve symlinks too; manifests must never upload files outside the checkout.
    result = (root / relative).resolve()
    result.relative_to(root.resolve())
    return result


def load_manifests(pattern: Path | None, root: Path) -> list[dict]:
    if pattern is None:
        return []
    records = []
    seen = set()
    for filename in sorted(glob.glob(str(pattern), recursive=True)):
        path = Path(filename).resolve()
        if not path.is_file():
            continue
        relative = path.relative_to(root.resolve()).as_posix()
        data = validate_manifest(json.loads(path.read_text(encoding="utf-8")))
        if data["junit"] in seen:
            raise ValueError(f"multiple execution manifests claim JUnit path {data['junit']}")
        seen.add(data["junit"])
        local_path(root, data["junit"])
        for artifact in data["artifacts"]:
            local_path(root, artifact["path"])
        records.append({"path": relative, "manifest": data})
    return records


def manifest_artifacts(manifest: dict, links: list, manifest_path: str) -> tuple[list, list[str]]:
    by_path = {}
    for link in links:
        by_path.setdefault(PurePosixPath(link.relative_path.replace("\\", "/")).as_posix(), link)
    result, warnings = [], []
    for artifact in manifest["artifacts"]:
        path = artifact["path"]
        link = by_path.get(path)
        if link is not None:
            result.append(link)
        elif artifact.get("required", True):
            warnings.append(f"Missing artifact: {path}")
    if manifest_path in by_path:
        result.append(by_path[manifest_path])
    return result, warnings
