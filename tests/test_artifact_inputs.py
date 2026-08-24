from pathlib import Path

import pytest
from artifact_inputs import (
    ArtifactConfig,
    ArtifactFile,
    collect_artifact_files,
    slugify_artifact_name,
)


def test_slugify_artifact_name_for_object_path():
    assert slugify_artifact_name("Test logs") == "test-logs"
    assert slugify_artifact_name("Server/Debug Logs!") == "server-debug-logs"


def test_collect_artifact_files_supports_glob_like_junit_input_path(tmp_path, monkeypatch, capsys):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    first = logs_dir / "test-logs-1.tar.gz"
    second = logs_dir / "test-logs-2.tar.gz"
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    artifact = ArtifactConfig(name="Test logs", input_path=Path("logs/test-logs-*.tar.gz"))
    result = collect_artifact_files([artifact])

    assert result == [
        ArtifactFile(
            config=artifact, local_path=first.resolve(), relative_path="logs/test-logs-1.tar.gz"
        ),
        ArtifactFile(
            config=artifact, local_path=second.resolve(), relative_path="logs/test-logs-2.tar.gz"
        ),
    ]
    assert capsys.readouterr().err == ""


def test_collect_artifact_files_supports_directory_recursively(tmp_path):
    logs_dir = tmp_path / "logs"
    first = logs_dir / "server.log"
    second = logs_dir / "nested" / "debug.log"
    first.parent.mkdir(parents=True, exist_ok=True)
    second.parent.mkdir(parents=True, exist_ok=True)
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")

    artifact = ArtifactConfig(name="Logs", input_path=logs_dir)
    result = collect_artifact_files([artifact])

    assert result == [
        ArtifactFile(config=artifact, local_path=second, relative_path="nested/debug.log"),
        ArtifactFile(config=artifact, local_path=first, relative_path="server.log"),
    ]


def test_collect_artifact_files_missing_path_warns_and_continues(tmp_path, capsys):
    artifact = ArtifactConfig(name="Missing logs", input_path=tmp_path / "missing")

    assert collect_artifact_files([artifact]) == []

    assert "WARN  additional artifact path does not exist" in capsys.readouterr().err


def test_collect_artifact_files_empty_glob_warns_and_continues(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    artifact = ArtifactConfig(name="Test logs", input_path=Path("test-logs-*.tar.gz"))

    assert collect_artifact_files([artifact]) == []

    err = capsys.readouterr().err
    assert "WARN  no files found for additional artifact" in err
    assert "artifact=Test logs" in err


def test_collect_artifact_files_rejects_duplicate_object_slugs():
    artifacts = [
        ArtifactConfig(name="Test logs", input_path=Path("a")),
        ArtifactConfig(name="Test_logs", input_path=Path("b")),
    ]

    with pytest.raises(ValueError, match="duplicate artifact object slug"):
        collect_artifact_files(artifacts)
