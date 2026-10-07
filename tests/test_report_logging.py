import json
import subprocess
import sys
from pathlib import Path

import pytest
from report_logging import configure_logging, logger


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        ("debug", ["debug", "info", "warning", "error", "fatal"]),
        ("info", ["info", "warning", "error", "fatal"]),
        ("warning", ["warning", "error", "fatal"]),
        ("error", ["error", "fatal"]),
        ("fatal", ["fatal"]),
    ],
)
def test_log_level_filters_messages(level, expected, capsys):
    configure_logging(level)
    logger.debug("debug")
    logger.info("info")
    logger.warning("warning")
    logger.error("error")
    logger.fatal("fatal")
    assert [line.split()[-1] for line in capsys.readouterr().err.splitlines()] == expected


def test_default_filters_warnings_from_plugin_helpers(tmp_path, capsys):
    from artifact_inputs import collect_artifact_files
    from object_store import log
    from plugin_config import ArtifactConfig, PlatformConfig
    from test_report_plugin import log as plugin_log
    from test_report_plugin import warn
    from xml_inputs import collect_xml_uploads

    collect_artifact_files([ArtifactConfig("logs", tmp_path / "missing")])
    collect_xml_uploads([PlatformConfig("linux", tmp_path / "missing")], "aggregate")
    plugin_log("progress")
    warn("warning")
    log("retry warning")
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("level", [None, "info", "debug"])
def test_cli_logging_preserves_report_summary(level, tmp_path):
    junit = tmp_path / "test.xml"
    junit.write_text(
        '<testsuite name="suite"><testcase name="passed"/>'
        '<testcase name="failed"><failure message="broken"/></testcase></testsuite>'
    )
    summary = tmp_path / "summary.json"
    command = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "tools" / "junit_html_report.py"),
        "--title",
        "tests",
        "--platform",
        f"linux={junit}",
        "--output",
        str(tmp_path / "report.html"),
        "--summary-json",
        str(summary),
    ]
    if level is not None:
        command.extend(["--log-level", level])
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert result.stdout == ""
    data = json.loads(summary.read_text())
    assert data["status_counts"] == {"SUCCESSFUL": 1, "FAILED": 1}
    assert data["logical_tests"] == 2
    assert len(data["failed_test_cases"]) == 1
    if level is None:
        assert result.stderr == ""
    else:
        assert "INFO  Wrote HTML report" in result.stderr
        assert "Built JUnit report model in" in result.stderr
        assert ("parsed file=" in result.stderr) == (level == "debug")


def test_quiet_cli_still_prints_generation_errors(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "tools" / "junit_html_report.py"),
            "--title",
            "tests",
            "--platform",
            f"linux={tmp_path}",
            "--template",
            str(tmp_path / "missing-template.html"),
            "--output",
            str(tmp_path / "report.html"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "FATAL Report generation failed:" in result.stderr
    assert "WARN" not in result.stderr
