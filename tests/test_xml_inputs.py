from pathlib import Path
import pytest
from xml_inputs import collect_job_xml_uploads, collect_xml_uploads, XmlUpload
from plugin_config import PlatformConfig


def test_collect_xml_uploads_file(tmp_path):
    f1 = tmp_path / "results.xml"
    f1.write_text("<testsuite/>")

    platforms = [PlatformConfig(name="linux", path=f1)]
    uploads = collect_xml_uploads(platforms, scope="full")

    assert uploads == [XmlUpload(local_path=f1, object_relative_path="linux/results.xml")]


def test_collect_xml_uploads_directory(tmp_path):
    d1 = tmp_path / "reports"
    d1.mkdir()
    f1 = d1 / "a.xml"
    f2 = d1 / "sub" / "b.xml"
    f1.parent.mkdir(parents=True, exist_ok=True)
    f2.parent.mkdir(parents=True, exist_ok=True)
    f1.write_text("<testsuite/>")
    f2.write_text("<testsuite/>")

    # Also add non-xml
    (d1 / "other.txt").write_text("text")

    platforms = [PlatformConfig(name="linux", path=d1)]
    uploads = collect_xml_uploads(platforms, scope="full")

    assert uploads == [
        XmlUpload(local_path=f1, object_relative_path="linux/a.xml"),
        XmlUpload(local_path=f2, object_relative_path="linux/sub/b.xml"),
    ]


def test_collect_xml_uploads_multiple_platforms(tmp_path):
    f1 = tmp_path / "p1.xml"
    f1.write_text("<testsuite/>")
    f2 = tmp_path / "p2.xml"
    f2.write_text("<testsuite/>")

    platforms = [
        PlatformConfig(name="linux", path=f1),
        PlatformConfig(name="macos", path=f2),
    ]
    uploads = collect_xml_uploads(platforms, scope="full")

    assert uploads == [
        XmlUpload(local_path=f1, object_relative_path="linux/p1.xml"),
        XmlUpload(local_path=f2, object_relative_path="macos/p2.xml"),
    ]


def test_collect_xml_uploads_no_files(tmp_path):
    d1 = tmp_path / "empty"
    d1.mkdir()

    platforms = [PlatformConfig(name="linux", path=d1)]
    uploads = collect_xml_uploads(platforms, scope="full")
    assert uploads == []


def test_collect_xml_uploads_missing_path(tmp_path):
    d1 = tmp_path / "missing"

    platforms = [PlatformConfig(name="linux", path=d1)]
    uploads = collect_xml_uploads(platforms, scope="full")
    assert uploads == []


def test_collect_xml_uploads_job_missing_path_errors(tmp_path):
    d1 = tmp_path / "missing"
    platforms = [PlatformConfig(name="linux", path=d1)]
    with pytest.raises(FileNotFoundError, match="platform path does not exist"):
        collect_xml_uploads(platforms, scope="job")


def test_collect_xml_uploads_job_no_files_errors(tmp_path):
    d1 = tmp_path / "empty"
    d1.mkdir()
    platforms = [PlatformConfig(name="linux", path=d1)]
    with pytest.raises(FileNotFoundError, match="no JUnit XML files found"):
        collect_xml_uploads(platforms, scope="job")


def test_collect_xml_uploads_path_traversal_protection(tmp_path):
    # If path is file, use name. If dir, use relative.
    # We should ensure we don't leak absolute paths or go up.
    f1 = tmp_path / "results.xml"
    f1.write_text("<testsuite/>")

    # Simulate a path that might look like it's trying to go up if not handled
    platforms = [PlatformConfig(name="linux", path=f1)]
    uploads = collect_xml_uploads(platforms, scope="full")
    assert uploads[0].object_relative_path == "linux/results.xml"


def test_collect_xml_uploads_glob(tmp_path, monkeypatch):
    d1 = tmp_path / "test-reports"
    d1.mkdir()
    f1 = d1 / "results.xml"
    f1.write_text("<testsuite/>")

    monkeypatch.chdir(tmp_path)
    platforms = [PlatformConfig(name="linux", path=Path("**/test-reports/*.xml"))]
    uploads = collect_xml_uploads(platforms, scope="full")

    assert len(uploads) == 1
    assert uploads[0].object_relative_path == "linux/test-reports/results.xml"
    assert uploads[0].local_path == f1.resolve()


def test_collect_job_xml_uploads_keeps_file_path_relative_without_variant_prefix(
    tmp_path,
):
    f1 = tmp_path / "results.xml"
    f1.write_text("<testsuite/>")

    uploads = collect_job_xml_uploads(
        junit_input_path=f1,
        variant="linux-haswell-release",
    )

    assert uploads == [
        XmlUpload(
            local_path=f1,
            object_relative_path="results.xml",
        )
    ]


def test_collect_job_xml_uploads_keeps_directory_paths_relative_without_variant_prefix(
    tmp_path,
):
    reports_dir = tmp_path / "reports"
    f1 = reports_dir / "unit.xml"
    f2 = reports_dir / "nested" / "integration.xml"
    f1.parent.mkdir(parents=True, exist_ok=True)
    f2.parent.mkdir(parents=True, exist_ok=True)
    f1.write_text("<testsuite/>")
    f2.write_text("<testsuite/>")

    uploads = collect_job_xml_uploads(
        junit_input_path=reports_dir,
        variant="linux",
    )

    assert uploads == [
        XmlUpload(local_path=f2, object_relative_path="nested/integration.xml"),
        XmlUpload(local_path=f1, object_relative_path="unit.xml"),
    ]


def test_collect_job_xml_uploads_keeps_glob_paths_relative_without_variant_prefix(
    tmp_path, monkeypatch
):
    reports_dir = tmp_path / "test-reports"
    reports_dir.mkdir()
    f1 = reports_dir / "results.xml"
    f1.write_text("<testsuite/>")

    monkeypatch.chdir(tmp_path)
    uploads = collect_job_xml_uploads(
        junit_input_path=Path("**/test-reports/*.xml"),
        variant="linux",
    )

    assert uploads == [
        XmlUpload(
            local_path=f1.resolve(),
            object_relative_path="test-reports/results.xml",
        )
    ]


def test_collect_job_xml_uploads_missing_path_errors(tmp_path):
    with pytest.raises(FileNotFoundError, match="junit_input_path does not exist"):
        collect_job_xml_uploads(
            junit_input_path=tmp_path / "missing",
            variant="linux",
        )


def test_collect_job_xml_uploads_no_files_errors(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    with pytest.raises(FileNotFoundError, match="no JUnit XML files found"):
        collect_job_xml_uploads(
            junit_input_path=empty_dir,
            variant="linux",
        )
