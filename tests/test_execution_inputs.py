import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest
from execution_inputs import ExecutionInputs, collect_execution_artifacts, collect_execution_inputs
from junit_report_model import ArtifactLink, build_report
from xml_inputs import XmlUpload


def write_execution(root, name="example", status="completed", exit_code=0, report="valid"):
    directory = root / name
    directory.mkdir()
    (directory / "runner.json").write_text('{"message":"log"}')
    (directory / "crash.dmp").write_bytes(b"dump")
    xml = root / f"{name}.xml"
    if report == "valid":
        xml.write_text(f'<testsuite name="suite"><testcase name="{name}" /></testsuite>')
    elif report == "failed":
        xml.write_text(
            f'<testsuite name="suite"><testcase name="{name}"><failure message="failed" /></testcase></testsuite>'
        )
    elif report == "empty":
        xml.write_text("<testsuite />")
    elif report == "malformed":
        xml.write_text("<testsuite>")
    metadata = root / "metadata"
    metadata.mkdir(exist_ok=True)
    manifest = {
        "version": 1,
        "execution_id": name,
        "name": name,
        "status": status,
        "exit_code": exit_code,
        "reports": [{"role": "junit", "path": xml.name, "required": True}],
        "artifacts": [{"role": "logs-and-dumps", "path": name, "required": False}],
    }
    (metadata / f"{name}.json").write_text(json.dumps(manifest))
    return xml


def collect(root, legacy=None):
    return collect_execution_inputs(root / "metadata", legacy or [], root / "stage", root)


def links_from_inputs(inputs):
    return [
        ArtifactLink(
            name="Test execution artifacts",
            relative_path=item.relative_path,
            key="logs.zip",
            url=f"https://reports/logs.zip#{item.relative_path}",
            size_bytes=1,
            execution_id=inputs.execution_ids[item.relative_path],
        )
        for item in inputs.artifact_files
    ]


def test_collect_reports_logs_dumps_and_manifest_with_exact_association(tmp_path):
    first = write_execution(tmp_path, "first")
    second = write_execution(tmp_path, "second")
    inputs = collect(tmp_path, [XmlUpload(first, first.name), XmlUpload(second, second.name)])
    assert len(inputs.xml_uploads) == 2
    assert len(inputs.artifact_files) == 8
    report = build_report(
        "report",
        [("linux", item.local_path) for item in inputs.xml_uploads],
        source_job_id="job",
        source_artifacts_by_job_id={"job": links_from_inputs(inputs)},
    )
    assert report.platforms == ["linux"]
    assert report.platform_execution_count == 2
    for suite in report.suites.values():
        for test_file in suite.test_files.values():
            for test in test_file.logical_tests.values():
                execution = test.executions["linux"]
                assert len(execution.source_artifacts) == 4
                assert {item.execution_id for item in execution.source_artifacts} == {
                    execution.name
                }


@pytest.mark.parametrize(
    "status,exit_code,xml",
    [
        ("failed", 3, "missing"),
        ("running", None, "missing"),
        ("completed", 0, "malformed"),
        ("completed", 0, "empty"),
        ("failed", 7, "valid"),
        ("running", None, "valid"),
        ("aborted", 143, "failed"),
    ],
)
def test_incomplete_execution_has_error_result(tmp_path, status, exit_code, xml):
    write_execution(tmp_path, status=status, exit_code=exit_code, report=xml)
    inputs = collect(tmp_path)
    synthetic = [item for item in inputs.xml_uploads if item.local_path.name == "launcher.xml"]
    assert len(synthetic) == 1
    document = ET.parse(synthetic[0].local_path)
    assert document.find(".//error") is not None
    assert document.find(".//property").attrib["value"] == "example"
    assert any(item.relative_path.endswith("crash.dmp") for item in inputs.artifact_files)


def test_valid_failing_report_does_not_add_duplicate_failure(tmp_path):
    write_execution(tmp_path, status="failed", exit_code=1, report="failed")
    inputs = collect(tmp_path)
    assert len(inputs.xml_uploads) == 1
    assert inputs.xml_uploads[0].local_path.name == "example.xml"


def test_malformed_original_is_preserved_as_artifact(tmp_path):
    original = write_execution(tmp_path, report="malformed")
    inputs = collect(tmp_path, [XmlUpload(original, original.name)])
    assert all(item.local_path != original for item in inputs.xml_uploads)
    assert original.read_text() == "<testsuite>"
    assert original in [item.local_path for item in inputs.artifact_files]


def test_aggregate_preserves_execution_association(tmp_path):
    write_execution(tmp_path)
    inputs = collect(tmp_path)
    job = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    aggregate = tmp_path / "aggregate"
    for item in inputs.xml_uploads:
        destination = aggregate / job / item.object_relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item.local_path, destination)
    report = build_report(
        "full", [("linux", aggregate)], source_artifacts_by_job_id={job: links_from_inputs(inputs)}
    )
    execution = next(
        iter(next(iter(report.suites["suite"].test_files.values())).logical_tests.values())
    ).executions["linux"]
    assert execution.execution_id == "example"
    assert len(execution.source_artifacts) == 4
    assert all(item.execution_id == "example" for item in execution.source_artifacts)


def test_legacy_reports_do_not_receive_managed_artifacts(tmp_path):
    from junit_report_model import source_artifacts_for_junit

    write_execution(tmp_path)
    inputs = collect(tmp_path)
    assert source_artifacts_for_junit(None, links_from_inputs(inputs), "legacy") == []
    legacy = tmp_path / "legacy.xml"
    legacy.write_text('<testsuite name="legacy"><testcase name="legacy" /></testsuite>')
    inputs = collect(tmp_path, [XmlUpload(legacy, legacy.name)])
    assert legacy in [item.local_path for item in inputs.xml_uploads]


@pytest.mark.parametrize("path", ["../outside.txt", "absolute"])
def test_rejects_paths_outside_checkout(tmp_path, path):
    write_execution(tmp_path)
    manifest_path = tmp_path / "metadata/example.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"][0]["path"] = (
        str(tmp_path.parent / "outside.txt") if path == "absolute" else path
    )
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="checkout-relative"):
        collect(tmp_path)


@pytest.mark.parametrize(
    "field,variable",
    [
        ("buildkite_job_id", "BUILDKITE_JOB_ID"),
        ("buildkite_build_id", "BUILDKITE_BUILD_ID"),
    ],
)
@pytest.mark.parametrize("matches", [False, True])
def test_filters_manifests_by_buildkite_identity(tmp_path, monkeypatch, field, variable, matches):
    write_execution(tmp_path)
    path = tmp_path / "metadata/example.json"
    manifest = json.loads(path.read_text())
    manifest[field] = "current" if matches else "old"
    path.write_text(json.dumps(manifest))
    monkeypatch.setenv(variable, "current")
    inputs = collect(tmp_path)
    assert len(inputs.xml_uploads) == (1 if matches else 0)
    assert bool(inputs.artifact_files) == matches


def test_missing_required_artifact_is_reported(tmp_path):
    write_execution(tmp_path)
    path = tmp_path / "metadata/example.json"
    manifest = json.loads(path.read_text())
    manifest["artifacts"].append({"role": "dump", "path": "missing.dmp", "required": True})
    path.write_text(json.dumps(manifest))
    inputs = collect(tmp_path)
    error = ET.parse(
        next(
            item.local_path for item in inputs.xml_uploads if item.local_path.name == "launcher.xml"
        )
    ).find(".//error")
    assert "Missing required artifact" in error.attrib["message"]


@pytest.mark.parametrize("claim", ["report", "artifact", "execution_id"])
def test_rejects_duplicate_execution_claims(tmp_path, claim):
    write_execution(tmp_path, "first")
    write_execution(tmp_path, "second")
    path = tmp_path / "metadata/second.json"
    manifest = json.loads(path.read_text())
    if claim == "report":
        manifest["reports"][0]["path"] = "first.xml"
    elif claim == "artifact":
        manifest["artifacts"][0]["path"] = "first"
    else:
        manifest["execution_id"] = "first"
    path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="multiple executions|duplicate execution_id"):
        collect(tmp_path)


@pytest.mark.parametrize(
    "group,role", [("artifacts", "dump"), ("reports", "junit"), ("reports", "log")]
)
def test_optional_missing_input_does_not_fail_execution(tmp_path, group, role):
    write_execution(tmp_path)
    path = tmp_path / "metadata/example.json"
    manifest = json.loads(path.read_text())
    manifest[group].append({"role": role, "path": "optional.dmp", "required": False})
    path.write_text(json.dumps(manifest))

    inputs = collect(tmp_path)

    assert len(inputs.xml_uploads) == 1
    assert inputs.xml_uploads[0].local_path.name == "example.xml"


@pytest.mark.parametrize("value", ["", ".", "./", "././"])
@pytest.mark.parametrize(
    "group,role", [("artifacts", "log"), ("reports", "junit"), ("reports", "log")]
)
def test_rejects_empty_and_dot_paths(tmp_path, value, group, role):
    write_execution(tmp_path)
    (tmp_path / "unrelated.txt").write_text("unrelated checkout data")
    path = tmp_path / "metadata/example.json"
    manifest = json.loads(path.read_text())
    manifest[group].append({"path": value, "role": role, "required": False})
    path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="must not be empty or dot paths"):
        collect(tmp_path)


@pytest.mark.parametrize(
    "xml",
    [
        '<testcase name="orphan" />',
        '<report><testcase name="orphan" /></report>',
        '<testsuite><wrapper><testcase name="nested" /></wrapper></testsuite>',
        '<testsuite><testsuite><testcase name="nested" /></testsuite></testsuite>',
    ],
)
@pytest.mark.parametrize("namespace", [False, True])
def test_unparseable_junit_structure_produces_launcher_error(tmp_path, xml, namespace):
    original = write_execution(tmp_path)
    document = ET.fromstring(xml)
    if namespace:
        for element in document.iter():
            element.tag = "{urn:junit}" + element.tag
    source = ET.tostring(document, encoding="unicode")
    original.write_text(source, encoding="utf-8")

    inputs = collect(tmp_path, [XmlUpload(original, original.name)])

    assert len(inputs.xml_uploads) == 1
    assert inputs.xml_uploads[0].local_path.name == "launcher.xml"
    error = ET.parse(inputs.xml_uploads[0].local_path).find(".//error")
    assert error is not None
    assert "direct testcase children of a testsuite" in error.attrib["message"]
    assert original.read_text(encoding="utf-8") == source
    assert original in [item.local_path for item in inputs.artifact_files]
    report = build_report("report", [("linux", inputs.xml_uploads[0].local_path)])
    assert report.status_counts["ERRORED"] == 1


def create_directory_link(link, target):
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        # Windows junctions exercise directory escapes without symlink privileges.
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
        )


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("has_files", [False, True])
def test_artifact_collection_rejects_outside_directory_links(tmp_path, nested, has_files):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    if has_files:
        (outside / "unrelated.txt").write_text("outside data")
    artifacts = checkout / "artifacts"
    artifacts.mkdir()
    link = artifacts / "link"
    create_directory_link(link, outside)
    inputs = ExecutionInputs()

    with pytest.raises(ValueError, match="execution artifact escapes checkout"):
        collect_execution_artifacts(checkout, inputs, artifacts if nested else link, "execution")
    assert inputs.artifact_files == []


@pytest.mark.parametrize("required", [False, True])
def test_manifest_rejects_nested_outside_directory_link(tmp_path, required):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    write_execution(checkout)
    outside = tmp_path / "outside"
    outside.mkdir()
    create_directory_link(checkout / "example" / "outside", outside)
    path = checkout / "metadata/example.json"
    manifest = json.loads(path.read_text())
    manifest["artifacts"][0]["required"] = required
    path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="execution artifact escapes checkout"):
        collect(checkout)


def test_declared_directory_link_inside_checkout_collects_files(tmp_path):
    target = tmp_path / "data"
    target.mkdir()
    log = target / "runner.log"
    log.write_text("runner data")
    link = tmp_path / "linked-data"
    create_directory_link(link, target)
    inputs = ExecutionInputs()

    collect_execution_artifacts(tmp_path, inputs, link, "execution")

    assert [artifact.local_path for artifact in inputs.artifact_files] == [log]
    assert inputs.execution_ids == {"data/runner.log": "execution"}
