"""Collect version 1 launcher manifests and normalize their JUnit inputs."""

from __future__ import annotations

import hashlib
import json
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from artifact_inputs import ArtifactFile, collect_artifact_files
from plugin_config import ArtifactConfig
from report_logging import logger
from xml_inputs import XmlUpload

EXECUTION_PROPERTY = "qdb.execution_id"


@dataclass
class ExecutionInputs:
    xml_uploads: list[XmlUpload] = field(default_factory=list)
    artifact_files: list[ArtifactFile] = field(default_factory=list)
    execution_ids: dict[str, str] = field(default_factory=dict)
    execution_names: dict[str, str] = field(default_factory=dict)


def resolve_input(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"manifest paths must be checkout-relative: {value!r}")
    resolved = (root / path).resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError(f"manifest path escapes checkout: {value!r}")
    return resolved


def mark_execution(document: ET.Element, execution_id: str) -> None:
    for suite in document.iter("testsuite"):
        properties = suite.find("properties")
        if properties is None:
            properties = ET.SubElement(suite, "properties")
        for item in list(properties):
            if item.attrib.get("name") == EXECUTION_PROPERTY:
                properties.remove(item)
        ET.SubElement(properties, "property", name=EXECUTION_PROPERTY, value=execution_id)


def collect_execution_artifacts(
    root: Path, result: ExecutionInputs, path: Path, execution_id: str
) -> None:
    files = sorted(path.rglob("*")) if path.is_dir() else [path]
    for file in files:
        if not file.is_file():
            continue
        resolved = file.resolve()
        if root != resolved and root not in resolved.parents:
            raise ValueError(f"execution artifact escapes checkout: {file}")
        relative = resolved.relative_to(root).as_posix()
        previous = result.execution_ids.get(relative)
        if previous is not None:
            if previous != execution_id:
                raise ValueError(f"artifact belongs to multiple executions: {relative}")
            continue
        result.execution_ids[relative] = execution_id
        result.artifact_files.append(
            ArtifactFile(ArtifactConfig("Test execution artifacts", root), resolved, relative)
        )


def collect_execution_manifest(root, manifest_path, manifest, staging, result, claimed):
    execution_id = manifest["execution_id"]
    name = manifest["name"]
    status = manifest["status"]
    result.execution_names[execution_id] = name
    collect_execution_artifacts(root, result, manifest_path, execution_id)
    errors: list[str] = []
    if status != "completed" or manifest.get("exit_code") != 0:
        errors.append(
            f"Launcher status: {status}; exit code: {manifest.get('exit_code', 'unavailable')}"
        )
    if manifest.get("error"):
        errors.append(str(manifest["error"]))
    reports_failed = False
    reports_parsed = 0
    report_errors = False
    for item in manifest.get("reports", []):
        path = resolve_input(root, item["path"])
        if item.get("role") != "junit":
            collect_execution_artifacts(root, result, path, execution_id)
            if item.get("required", False) and not path.exists():
                errors.append(f"Missing required report: {item['path']}")
                report_errors = True
            continue
        if path in claimed:
            raise ValueError(f"JUnit report belongs to multiple executions: {path}")
        claimed.add(path)
        if not path.is_file():
            if item.get("required", True):
                errors.append(f"Missing JUnit report: {item['path']}")
                report_errors = True
            continue
        collect_execution_artifacts(root, result, path, execution_id)
        try:
            document = ET.parse(path).getroot()
            if not list(document.iter("testcase")):
                raise ValueError("report contains no test cases")
        except (ET.ParseError, ValueError) as exc:
            errors.append(f"Invalid JUnit report {item['path']}: {exc}")
            report_errors = True
            continue
        reports_parsed += 1
        reports_failed |= (
            next(document.iter("failure"), None) is not None
            or next(document.iter("error"), None) is not None
        )
        mark_execution(document, execution_id)
        relative = path.relative_to(root).as_posix()
        key = hashlib.sha256(relative.encode()).hexdigest()
        destination = staging / key / path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(document).write(destination, encoding="utf-8", xml_declaration=True)
        result.xml_uploads.append(XmlUpload(destination, f"executions/{key}/{path.name}"))

    for item in manifest.get("artifacts", []):
        path = resolve_input(root, item["path"])
        collect_execution_artifacts(root, result, path, execution_id)
        if item.get("required", False) and not path.exists():
            errors.append(f"Missing required artifact: {item['path']}")
            report_errors = True

    # A failed process with valid failing cases is already represented. A hard
    # kill, launch failure, or missing/invalid report needs its own result.
    if (
        report_errors
        or not reports_parsed
        or errors
        and (not reports_failed or status in {"running", "aborted"})
    ):
        document = ET.Element("testsuite", name="Test executions")
        testcase = ET.SubElement(
            document,
            "testcase",
            name=name,
            classname="launcher",
            time=str(manifest.get("duration_seconds", 0)),
        )
        if errors:
            message = "; ".join(errors)
            ET.SubElement(testcase, "error", message=message).text = message
            logger.warning("%s: %s", name, message)
        mark_execution(document, execution_id)
        key = hashlib.sha256(manifest_path.relative_to(root).as_posix().encode()).hexdigest()
        destination = staging / key / "launcher.xml"
        destination.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(document).write(destination, encoding="utf-8", xml_declaration=True)
        result.xml_uploads.append(XmlUpload(destination, f"executions/{key}/launcher.xml"))


def collect_execution_inputs(
    input_path: Path,
    legacy_xml: list[XmlUpload],
    staging: Path,
    root: Path | None = None,
) -> ExecutionInputs:
    root = (root or Path.cwd()).resolve()
    result = ExecutionInputs()
    claimed: set[Path] = set()
    execution_ids: set[str] = set()
    staging.mkdir(parents=True, exist_ok=True)

    for manifest_input in collect_artifact_files(
        [ArtifactConfig("Execution manifests", input_path)]
    ):
        manifest_path = manifest_input.local_path.resolve()
        if manifest_path.suffix != ".json":
            continue
        if root != manifest_path and root not in manifest_path.parents:
            raise ValueError(f"manifest is outside checkout: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if any(
            manifest.get(field) is not None
            and os.environ.get(variable) is not None
            and manifest[field] != os.environ[variable]
            for field, variable in (
                ("buildkite_build_id", "BUILDKITE_BUILD_ID"),
                ("buildkite_job_id", "BUILDKITE_JOB_ID"),
            )
        ):
            continue
        if manifest.get("version") != 1:
            raise ValueError(f"unsupported execution manifest version: {manifest_path}")
        execution_id = manifest.get("execution_id")
        name = manifest.get("name")
        status = manifest.get("status")
        if (
            not isinstance(execution_id, str)
            or not execution_id
            or not isinstance(name, str)
            or not name
        ):
            raise ValueError(f"manifest requires execution_id and name: {manifest_path}")
        if execution_id in execution_ids:
            raise ValueError(f"duplicate execution_id: {execution_id}")
        execution_ids.add(execution_id)
        if status not in {"running", "completed", "failed", "aborted"}:
            raise ValueError(f"invalid execution status: {status!r}")
        collect_execution_manifest(root, manifest_path, manifest, staging, result, claimed)

    result.xml_uploads.extend(xml for xml in legacy_xml if xml.local_path.resolve() not in claimed)
    return result
