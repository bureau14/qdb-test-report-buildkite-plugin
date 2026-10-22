import json
import xml.etree.ElementTree as ET

import pytest
from execution_inputs import collect_execution_inputs
from junit_report_model import ArtifactLink, build_report, local_name


@pytest.mark.parametrize("existing_property", [False, True])
@pytest.mark.parametrize("namespace", ["", ' xmlns="urn:junit"', ' xmlns:p="urn:junit"'])
@pytest.mark.parametrize(
    ("result", "expected"),
    [(None, "SUCCESSFUL"), ("failure", "FAILED"), ("error", "ERRORED"), ("skipped", "SKIPPED")],
)
def test_manifest_preserves_namespaced_status_and_artifact_association(
    tmp_path, namespace, result, expected, existing_property
):
    prefix = "p:" if "xmlns:p" in namespace else ""
    xml = ET.Element(prefix + "testsuites")
    suite = ET.SubElement(xml, prefix + "testsuite", name="suite")
    if existing_property:
        properties = ET.SubElement(suite, prefix + "properties")
        ET.SubElement(properties, prefix + "property", name="qdb.execution_id", value="stale")
    case = ET.SubElement(suite, prefix + "testcase", name="case")
    if result:
        ET.SubElement(case, prefix + result, message="reason").text = "details"
    ET.SubElement(case, prefix + "system-out").text = "runner output"
    ET.SubElement(case, prefix + "system-err").text = "runner error"
    source = ET.tostring(xml, encoding="unicode").replace(
        "<" + prefix + "testsuites", "<" + prefix + "testsuites" + namespace, 1
    )
    report_path = tmp_path / "report.xml"
    report_path.write_text(source, encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "execution_id": "execution",
                "name": "launch",
                "status": "completed",
                "exit_code": 1 if result in {"failure", "error"} else 0,
                "reports": [{"path": "report.xml", "role": "junit"}],
            }
        ),
        encoding="utf-8",
    )

    inputs = collect_execution_inputs(manifest_path, [], tmp_path / "stage", tmp_path)

    assert len(inputs.xml_uploads) == 1
    assert inputs.xml_uploads[0].local_path.name == "report.xml"
    assert report_path.read_text(encoding="utf-8") == source
    rewritten = ET.parse(inputs.xml_uploads[0].local_path).getroot()
    ids = [
        element.attrib["value"]
        for element in rewritten.iter()
        if local_name(element) == "property" and element.attrib.get("name") == "qdb.execution_id"
    ]
    assert ids == ["execution"]
    artifact = ArtifactLink("Logs", "runner.log", "logs.zip", None, 1, execution_id="execution")
    report = build_report(
        "Report",
        [("linux", inputs.xml_uploads[0].local_path)],
        source_job_id="job",
        source_artifacts_by_job_id={"job": [artifact]},
    )
    execution = next(
        iter(next(iter(report.suites["suite"].test_files.values())).logical_tests.values())
    ).executions["linux"]
    assert execution.execution_id == "execution"
    assert execution.source_artifacts == [artifact]
    assert execution.status == expected
    if result:
        assert execution.reason == "reason"
    if result in {"failure", "error"}:
        assert "details" in execution.output
        assert "runner output" in execution.output
        assert "runner error" in execution.output
