from unittest.mock import MagicMock
from pathlib import Path
import json
import re
import pytest
from test_report_plugin import (
    build_aggregate_xml_source_links,
    build_job_xml_source_links,
    run_report_generation,
    upload_extra_artifacts,
    upload_report_artifacts,
    GenerationResult,
    ObjectStoreContext,
    XmlSourceLink,
    main,
)
from artifact_inputs import ArtifactConfig, ArtifactFile
from plugin_config import PluginConfig, PlatformConfig
from xml_inputs import XmlUpload


def noop_collect_full_scope_job_summaries(**kwargs):
    return {}


@pytest.fixture(autouse=True)
def stub_full_scope_job_summaries(monkeypatch):
    monkeypatch.setattr(
        "test_report_plugin.collect_full_scope_job_summaries",
        noop_collect_full_scope_job_summaries,
    )
    monkeypatch.setattr(
        "test_report_plugin.collect_full_scope_job_summaries_for_xml",
        noop_collect_full_scope_job_summaries,
    )
    from object_store import ObjectAuth, StoreConfig

    monkeypatch.setattr(
        "test_report_plugin.resolve_object_store_context",
        lambda: ObjectStoreContext(
            StoreConfig("s3", "s3://bucket/prefix"), ObjectAuth(), "bucket", "prefix"
        ),
    )


def test_run_report_generation(tmp_path):
    # Setup mock JUnit XML
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    xml_file = xml_dir / "test.xml"
    xml_file.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="suite1" tests="1" failures="0">
    <testcase name="test1" />
  </testsuite>
</testsuites>
""")

    output_dir = tmp_path / "output"

    config = PluginConfig(
        scope="job",
        title="Test Report",
        variant="linux",
        execution_name="Execution",
        project_id="project",
        git_ref="refs/heads/main",
        build_id="1",
        job_id="1",
        build_url="http://example.com/build/1",
        platforms=[PlatformConfig(name="linux", path=xml_dir)],
        only_failures=False,
        annotate=True,
        fail_on_test_failures=False,
    )

    xml_url = "https://reports.example.com/project/build-1/linux/test.xml"
    result = run_report_generation(
        config,
        output_dir,
        xml_source_links={
            xml_file.resolve(): XmlSourceLink("project/build-1/linux/test.xml", xml_url)
        },
    )

    assert result.html_path.exists()
    assert result.summary_path.exists()
    html = result.html_path.read_text(encoding="utf-8")
    assert "test1 - linux" in html
    assert xml_url in html
    assert not (output_dir / "generation.log").exists()
    assert not hasattr(result, "log_path")


def test_job_xml_source_links_use_uploaded_keys_and_artifacts_domain(tmp_path):
    from object_store import ObjectAuth, StoreConfig

    xml = tmp_path / "nested" / "results.xml"
    xml.parent.mkdir()
    xml.write_text("<testsuites />", encoding="utf-8")
    config = PluginConfig(
        scope="job",
        title="Test Report",
        variant="linux",
        execution_name=None,
        project_id="project",
        git_ref="refs/heads/main",
        build_id="build-1",
        job_id="job-1",
        build_url=None,
        platforms=[],
        only_failures=False,
        annotate=False,
        fail_on_test_failures=False,
    )
    context = ObjectStoreContext(
        StoreConfig("s3", "s3://bucket/prefix", artifacts_domain="reports.example.com"),
        ObjectAuth(),
        "bucket",
        "prefix",
    )

    links = build_job_xml_source_links(
        config, [XmlUpload(local_path=xml, object_relative_path="nested/results.xml")], context
    )

    link = links[xml.resolve()]
    assert link.key == (
        "prefix/project/refs/heads/main/reports/builds/build-1/variants/linux/jobs/job-1/"
        "xml/nested/results.xml"
    )
    assert link.url == f"https://reports.example.com/{link.key}"


def test_aggregate_xml_source_links_preserve_discovered_keys_and_no_domain(tmp_path):
    from object_store import ObjectAuth, StoreConfig
    from report_downloads import DownloadedJobXml, JobXmlObject

    first = tmp_path / "linux" / "job-1" / "results.xml"
    second = tmp_path / "linux" / "job-2" / "results.xml"
    for path in (first, second):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<testsuites />", encoding="utf-8")
    downloaded = [
        DownloadedJobXml(
            JobXmlObject("linux", "job-1", "original/one.xml", "results.xml", 1), first
        ),
        DownloadedJobXml(
            JobXmlObject("linux", "job-2", "original/two.xml", "results.xml", 1), second
        ),
    ]
    context = ObjectStoreContext(
        StoreConfig("s3", "s3://bucket/prefix"), ObjectAuth(), "bucket", "prefix"
    )

    links = build_aggregate_xml_source_links(downloaded, context)

    assert links[first.resolve()].key == "original/one.xml"
    assert links[second.resolve()].key == "original/two.xml"
    assert links[first.resolve()].url is None
    assert links[second.resolve()].url is None


def test_upload_report_artifacts(monkeypatch, tmp_path):
    # Setup paths
    html_path = tmp_path / "index.html"
    html_path.write_text("html")
    summary_path = tmp_path / "summary.json"
    summary_path.write_text("{}")
    xml_path = tmp_path / "test.xml"
    xml_path.write_text("xml")

    generation = GenerationResult(
        html_path=html_path,
        summary_path=summary_path,
    )

    xml_uploads = [XmlUpload(local_path=xml_path, object_relative_path="test.xml")]

    config = PluginConfig(
        scope="job",
        title="Test Report",
        variant="linux",
        execution_name=None,
        project_id="project",
        git_ref="refs/heads/main",
        build_id="1",
        job_id="123",
        build_url=None,
        platforms=[],
        only_failures=False,
        annotate=True,
        fail_on_test_failures=False,
    )

    # Mocks
    mock_s3 = MagicMock()
    mock_ssm = MagicMock()
    monkeypatch.setattr("test_report_plugin.aws_clients", lambda: (mock_s3, mock_ssm))

    from object_store import StoreConfig, ObjectAuth

    monkeypatch.setattr(
        "test_report_plugin.load_store_config",
        lambda ssm: StoreConfig(
            backend="s3",
            destination="s3://my-bucket/prefix",
            artifacts_domain="reports.example.com",
        ),
    )
    monkeypatch.setattr(
        "test_report_plugin.resolve_object_auth", lambda *args, **kwargs: ObjectAuth()
    )

    uploaded = []

    def fake_upload_file(cfg, auth, bucket, key, local_path, **kwargs):
        uploaded.append((bucket, key, local_path, kwargs))
        from object_store import PublishedObject

        return PublishedObject(
            bucket=bucket,
            key=key,
            url=f"https://{cfg.artifacts_domain}/{key}",
            size_bytes=100,
        )

    monkeypatch.setattr("test_report_plugin.upload_file", fake_upload_file)

    upload_report_artifacts(config, generation, xml_uploads, None)

    assert len(uploaded) == 3
    # XML upload check (index 2 now)
    assert (
        uploaded[2][1]
        == "prefix/project/refs/heads/main/reports/builds/1/variants/linux/jobs/123/xml/test.xml"
    )
    assert uploaded[2][3]["content_type"] == "application/xml"
    assert uploaded[2][3]["content_disposition"] == "attachment"


def test_upload_extra_artifacts_returns_summary_metadata(monkeypatch, tmp_path):
    log_file = tmp_path / "test-logs-1.tar.gz"
    log_file.write_text("logs", encoding="utf-8")
    artifact = ArtifactConfig(name="Test logs", input_path=Path("test-logs-*.tar.gz"))
    artifact_file = ArtifactFile(
        config=artifact,
        local_path=log_file,
        relative_path="test-logs-1.tar.gz",
    )
    config = PluginConfig(
        scope="job",
        title="Test Report",
        variant="linux",
        execution_name=None,
        project_id="project",
        git_ref="refs/heads/main",
        build_id="1",
        job_id="123",
        build_url=None,
        platforms=[],
        only_failures=False,
        annotate=True,
        fail_on_test_failures=False,
    )

    from object_store import ObjectAuth, StoreConfig, PublishedObject

    store_cfg = StoreConfig(
        backend="s3",
        destination="s3://my-bucket/prefix",
        artifacts_domain="reports.example.com",
    )
    context = ObjectStoreContext(
        store_cfg=store_cfg,
        auth=ObjectAuth(),
        bucket="my-bucket",
        prefix="prefix",
    )
    uploaded = []

    def fake_upload_file(cfg, auth, bucket, key, local_path, **kwargs):
        uploaded.append((bucket, key, local_path, kwargs))
        return PublishedObject(
            bucket=bucket,
            key=key,
            url=f"https://{cfg.artifacts_domain}/{key}",
            size_bytes=local_path.stat().st_size,
        )

    monkeypatch.setattr("test_report_plugin.upload_file", fake_upload_file)

    metadata = upload_extra_artifacts(config, [artifact_file], context)

    assert uploaded[0][1] == (
        "prefix/project/refs/heads/main/reports/builds/1/variants/linux/jobs/123/"
        "artifacts/test-logs/test-logs-1.tar.gz"
    )
    assert uploaded[0][3]["content_type"] == "application/gzip"
    assert uploaded[0][3]["content_disposition"] == "attachment"
    assert metadata == [
        {
            "name": "Test logs",
            "input_path": "test-logs-*.tar.gz",
            "files": [
                {
                    "relative_path": "test-logs-1.tar.gz",
                    "key": uploaded[0][1],
                    "url": f"https://reports.example.com/{uploaded[0][1]}",
                    "size_bytes": 4,
                }
            ],
            "warnings": [],
        }
    ]


def test_main_job_logs_uploaded_html_url(monkeypatch, tmp_path, capsys):
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    (xml_dir / "test.xml").write_text("<testsuites />", encoding="utf-8")

    monkeypatch.setattr(
        "os.environ",
        {
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE": "Job Tests",
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_VARIANT": "linux",
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_JUNIT_INPUT_PATH": str(xml_dir),
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_ANNOTATE": "false",
            "BUILDKITE_PIPELINE_SLUG": "project",
            "BUILDKITE_BUILD_ID": "build-1",
            "BUILDKITE_JOB_ID": "job-1",
            "BUILDKITE_BRANCH": "main",
        },
    )

    def fake_run_report_generation(config, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        html_path = output_dir / "index.html"
        summary_path = output_dir / "summary.json"
        html_path.write_text("html", encoding="utf-8")
        summary_path.write_text(
            '{"root_status":"SUCCESSFUL","logical_tests":0,"targets":1,"status_counts":{}}',
            encoding="utf-8",
        )
        return GenerationResult(html_path=html_path, summary_path=summary_path)

    def fake_upload_report_artifacts(config, generation, xml_uploads, store_context=None):
        from object_store import PublishedObject

        return {
            "html": PublishedObject(
                "bucket",
                "prefix/job/index.html",
                "https://reports.example.com/job/index.html",
                4,
            ),
            "summary": PublishedObject("bucket", "prefix/job/summary.json", None, 2),
        }

    monkeypatch.setattr("test_report_plugin.run_report_generation", fake_run_report_generation)
    monkeypatch.setattr("test_report_plugin.upload_report_artifacts", fake_upload_report_artifacts)

    assert main() == 0
    assert "HTML report: https://reports.example.com/job/index.html" in capsys.readouterr().err


def test_main_job_annotation_context(monkeypatch, tmp_path):
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    (xml_dir / "test.xml").write_text("<testsuites />", encoding="utf-8")

    monkeypatch.setattr(
        "os.environ",
        {
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE": "Job Tests",
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_VARIANT": "linux",
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_JUNIT_INPUT_PATH": str(xml_dir),
            "BUILDKITE_PIPELINE_SLUG": "project",
            "BUILDKITE_BUILD_ID": "build-1",
            "BUILDKITE_JOB_ID": "job-1",
            "BUILDKITE_BRANCH": "main",
        },
    )

    def fake_run_report_generation(config, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        html_path = output_dir / "index.html"
        summary_path = output_dir / "summary.json"
        html_path.write_text("html", encoding="utf-8")
        summary_path.write_text(
            '{"root_status":"SUCCESSFUL","logical_tests":0,"targets":1,"status_counts":{}}',
            encoding="utf-8",
        )
        return GenerationResult(html_path=html_path, summary_path=summary_path)

    def fake_upload_report_artifacts(config, generation, xml_uploads, store_context=None):
        from object_store import PublishedObject

        return {
            "html": PublishedObject(
                "bucket",
                "prefix/job/index.html",
                "https://reports.example.com/job/index.html",
                4,
            )
        }

    annotations = []
    monkeypatch.setattr("test_report_plugin.run_report_generation", fake_run_report_generation)
    monkeypatch.setattr("test_report_plugin.upload_report_artifacts", fake_upload_report_artifacts)
    monkeypatch.setattr(
        "test_report_plugin.create_buildkite_annotation",
        lambda body, context, style, priority, scope: annotations.append(
            (body, context, style, priority, scope)
        ),
    )

    assert main() == 0
    assert annotations == [(annotations[0][0], "test-report:linux:job-1", "warning", 10, "job")]
    assert "Open full report" in annotations[0][0]


def test_main_job_collects_xml_from_junit_input_path(monkeypatch, tmp_path):
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    (xml_dir / "test.xml").write_text("<testsuites />", encoding="utf-8")

    monkeypatch.setattr(
        "os.environ",
        {
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE": "Job Tests",
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_VARIANT": "linux",
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_JUNIT_INPUT_PATH": str(xml_dir),
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_ANNOTATE": "false",
            "BUILDKITE_PIPELINE_SLUG": "project",
            "BUILDKITE_BUILD_ID": "build-1",
            "BUILDKITE_JOB_ID": "job-1",
            "BUILDKITE_BRANCH": "main",
        },
    )

    collected = []

    def fake_collect_job_xml_uploads(junit_input_path, variant):
        collected.append((junit_input_path, variant))
        return [XmlUpload(local_path=xml_dir / "test.xml", object_relative_path="test.xml")]

    def fake_run_report_generation(config, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        html_path = output_dir / "index.html"
        summary_path = output_dir / "summary.json"
        html_path.write_text("html", encoding="utf-8")
        summary_path.write_text(
            '{"root_status":"SUCCESSFUL","status_counts":{}}',
            encoding="utf-8",
        )
        return GenerationResult(html_path=html_path, summary_path=summary_path)

    uploaded_xml = []
    monkeypatch.setattr("test_report_plugin.collect_job_xml_uploads", fake_collect_job_xml_uploads)
    monkeypatch.setattr("test_report_plugin.run_report_generation", fake_run_report_generation)
    monkeypatch.setattr(
        "test_report_plugin.upload_report_artifacts",
        lambda config, generation, xml_uploads, store_context=None: (
            uploaded_xml.extend(xml_uploads) or {}
        ),
    )

    assert main() == 0
    assert collected == [(xml_dir, "linux")]
    assert [xml.object_relative_path for xml in uploaded_xml] == ["test.xml"]


def test_main_job_uses_tempfile_staging_by_default(monkeypatch, tmp_path):
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    (xml_dir / "test.xml").write_text("<testsuites />", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "os.environ",
        {
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE": "Job Tests",
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_VARIANT": "linux",
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_JUNIT_INPUT_PATH": str(xml_dir),
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_ANNOTATE": "false",
            "BUILDKITE_PIPELINE_SLUG": "project",
            "BUILDKITE_BUILD_ID": "build-1",
            "BUILDKITE_JOB_ID": "job-1",
            "BUILDKITE_BRANCH": "main",
        },
    )

    generated_dirs = []

    def fake_run_report_generation(config, output_dir, **kwargs):
        generated_dirs.append(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        html_path = output_dir / "index.html"
        summary_path = output_dir / "summary.json"
        html_path.write_text("html", encoding="utf-8")
        summary_path.write_text(
            '{"root_status":"SUCCESSFUL","status_counts":{}}',
            encoding="utf-8",
        )
        return GenerationResult(html_path=html_path, summary_path=summary_path)

    def fake_upload_report_artifacts(config, generation, xml_uploads, store_context=None):
        assert generation.html_path.exists()
        assert generation.summary_path.exists()
        return {}

    monkeypatch.setattr("test_report_plugin.run_report_generation", fake_run_report_generation)
    monkeypatch.setattr("test_report_plugin.upload_report_artifacts", fake_upload_report_artifacts)

    assert main() == 0
    assert len(generated_dirs) == 1
    assert ".buildkite-test-report" not in generated_dirs[0].parts
    assert generated_dirs[0].name == "report"
    assert not generated_dirs[0].exists()
    assert not (tmp_path / ".buildkite-test-report").exists()


def test_main_job_defaults_to_fail_when_summary_has_failed_tests(monkeypatch, tmp_path, capsys):
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    (xml_dir / "test.xml").write_text("<testsuites />", encoding="utf-8")

    monkeypatch.setattr(
        "os.environ",
        {
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE": "Job Tests",
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_VARIANT": "linux",
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_JUNIT_INPUT_PATH": str(xml_dir),
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_ANNOTATE": "false",
            "BUILDKITE_PIPELINE_SLUG": "project",
            "BUILDKITE_BUILD_ID": "build-1",
            "BUILDKITE_JOB_ID": "job-1",
            "BUILDKITE_BRANCH": "main",
        },
    )

    def fake_run_report_generation(config, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        html_path = output_dir / "index.html"
        summary_path = output_dir / "summary.json"
        html_path.write_text("html", encoding="utf-8")
        summary_path.write_text(
            '{"root_status":"FAILED","status_counts":{"FAILED":1}}',
            encoding="utf-8",
        )
        return GenerationResult(html_path=html_path, summary_path=summary_path)

    monkeypatch.setattr("test_report_plugin.run_report_generation", fake_run_report_generation)
    monkeypatch.setattr(
        "test_report_plugin.upload_report_artifacts",
        lambda config, generation, xml_uploads, store_context=None: {},
    )

    assert main() == 64
    assert "fail_on_test_failures=true" in capsys.readouterr().err


def test_main_job_fails_when_summary_has_errored_tests(monkeypatch, tmp_path):
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    (xml_dir / "test.xml").write_text("<testsuites />", encoding="utf-8")

    monkeypatch.setattr(
        "os.environ",
        {
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE": "Job Tests",
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_VARIANT": "linux",
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_JUNIT_INPUT_PATH": str(xml_dir),
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_ANNOTATE": "false",
            "BUILDKITE_PIPELINE_SLUG": "project",
            "BUILDKITE_BUILD_ID": "build-1",
            "BUILDKITE_JOB_ID": "job-1",
            "BUILDKITE_BRANCH": "main",
        },
    )

    def fake_run_report_generation(config, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        html_path = output_dir / "index.html"
        summary_path = output_dir / "summary.json"
        html_path.write_text("html", encoding="utf-8")
        summary_path.write_text(
            '{"root_status":"ERRORED","status_counts":{"ERRORED":1}}',
            encoding="utf-8",
        )
        return GenerationResult(html_path=html_path, summary_path=summary_path)

    monkeypatch.setattr("test_report_plugin.run_report_generation", fake_run_report_generation)
    monkeypatch.setattr(
        "test_report_plugin.upload_report_artifacts",
        lambda config, generation, xml_uploads, store_context=None: {},
    )

    assert main() == 64


def test_main_full_defaults_to_ignore_failed_tests_for_exit_status(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "os.environ",
        {
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE": "Full Tests",
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_ANNOTATE": "false",
            "BUILDKITE_PIPELINE_SLUG": "project",
            "BUILDKITE_BUILD_ID": "build-1",
            "BUILDKITE_BRANCH": "main",
        },
    )

    from object_store import ObjectAuth, StoreConfig

    monkeypatch.setattr(
        "test_report_plugin.resolve_object_store_context",
        lambda: __import__(
            "test_report_plugin", fromlist=["ObjectStoreContext"]
        ).ObjectStoreContext(
            StoreConfig("s3", "s3://bucket/prefix"), ObjectAuth(), "bucket", "prefix"
        ),
    )

    def fake_collect_full_scope_xml(**kwargs):
        staged = kwargs["output_dir"] / "linux" / "job-1" / "test.xml"
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text("<testsuites />", encoding="utf-8")
        return []

    def fake_run_report_generation(config, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        html_path = output_dir / "index.html"
        summary_path = output_dir / "summary.json"
        html_path.write_text("html", encoding="utf-8")
        summary_path.write_text(
            '{"root_status":"FAILED","status_counts":{"FAILED":1}}',
            encoding="utf-8",
        )
        return GenerationResult(html_path=html_path, summary_path=summary_path)

    monkeypatch.setattr("test_report_plugin.collect_full_scope_xml", fake_collect_full_scope_xml)
    monkeypatch.setattr("test_report_plugin.run_report_generation", fake_run_report_generation)
    monkeypatch.setattr(
        "test_report_plugin.upload_report_artifacts",
        lambda config, generation, xml_uploads, store_context=None: {},
    )

    assert main() == 0


def test_main_full_annotation_context(monkeypatch, tmp_path):
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    (xml_dir / "test.xml").write_text("<testsuites />", encoding="utf-8")

    monkeypatch.setattr(
        "os.environ",
        {
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE": "Full Tests",
            "BUILDKITE_PIPELINE_SLUG": "project",
            "BUILDKITE_BUILD_ID": "build-1",
            "BUILDKITE_BRANCH": "main",
        },
    )

    from object_store import ObjectAuth, StoreConfig

    monkeypatch.setattr(
        "test_report_plugin.resolve_object_store_context",
        lambda: __import__(
            "test_report_plugin", fromlist=["ObjectStoreContext"]
        ).ObjectStoreContext(
            StoreConfig("s3", "s3://bucket/prefix", artifacts_domain="reports.example.com"),
            ObjectAuth(),
            "bucket",
            "prefix",
        ),
    )

    def fake_collect_full_scope_xml(**kwargs):
        from report_downloads import DownloadedJobXml, JobXmlObject

        staged = kwargs["output_dir"] / "linux" / "job-1" / "test.xml"
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text("<testsuites />", encoding="utf-8")
        return [
            DownloadedJobXml(
                object=JobXmlObject(
                    variant="linux",
                    job_id="job-1",
                    key="prefix/project/refs/heads/main/reports/builds/build-1/variants/linux/jobs/job-1/xml/test.xml",
                    relative_path="test.xml",
                    size_bytes=15,
                ),
                local_path=staged,
            )
        ]

    monkeypatch.setattr("test_report_plugin.collect_full_scope_xml", fake_collect_full_scope_xml)

    def fake_run_report_generation(config, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        html_path = output_dir / "index.html"
        summary_path = output_dir / "summary.json"
        html_path.write_text("html", encoding="utf-8")
        summary_path.write_text(
            '{"root_status":"SUCCESSFUL","logical_tests":0,"targets":1,"status_counts":{}}',
            encoding="utf-8",
        )
        return GenerationResult(html_path=html_path, summary_path=summary_path)

    def fake_upload_report_artifacts(config, generation, xml_uploads, store_context=None):
        from object_store import PublishedObject

        return {
            "html": PublishedObject(
                "bucket",
                "prefix/full/index.html",
                "https://reports.example.com/full/index.html",
                4,
            )
        }

    annotations = []
    monkeypatch.setattr("test_report_plugin.run_report_generation", fake_run_report_generation)
    monkeypatch.setattr("test_report_plugin.upload_report_artifacts", fake_upload_report_artifacts)
    monkeypatch.setattr(
        "test_report_plugin.create_buildkite_annotation",
        lambda body, context, style, priority, scope: annotations.append(
            (body, context, style, priority, scope)
        ),
    )

    assert main() == 0
    assert annotations == [(annotations[0][0], "test-report:full", "success", 10, "build")]


def test_main_full_zero_xml_creates_error_annotation(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        "os.environ",
        {
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE": "Full Tests",
            "BUILDKITE_PIPELINE_SLUG": "project",
            "BUILDKITE_BUILD_ID": "build-1",
            "BUILDKITE_BRANCH": "main",
        },
    )

    from object_store import ObjectAuth, StoreConfig

    monkeypatch.setattr(
        "test_report_plugin.resolve_object_store_context",
        lambda: __import__(
            "test_report_plugin", fromlist=["ObjectStoreContext"]
        ).ObjectStoreContext(
            StoreConfig("s3", "s3://bucket/prefix", artifacts_domain="reports.example.com"),
            ObjectAuth(),
            "bucket",
            "prefix",
        ),
    )

    def fake_collect_full_scope_xml(**kwargs):
        staged = kwargs["output_dir"] / "linux" / "job-1" / "test.xml"
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text("<testsuites />", encoding="utf-8")
        return []

    def fake_run_report_generation(config, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        html_path = output_dir / "index.html"
        summary_path = output_dir / "summary.json"
        html_path.write_text("html", encoding="utf-8")
        summary_path.write_text(
            '{"root_status":"SUCCESSFUL","logical_tests":1,"targets":2,"status_counts":{"SUCCESSFUL":1}}',
            encoding="utf-8",
        )
        return GenerationResult(html_path=html_path, summary_path=summary_path)

    def fake_upload_report_artifacts(config, generation, xml_uploads, store_context=None):
        from object_store import PublishedObject

        return {
            "html": PublishedObject(
                "bucket",
                "prefix/full/index.html",
                "https://reports.example.com/full/index.html",
                4,
            )
        }

    annotations = []
    monkeypatch.setattr("test_report_plugin.collect_full_scope_xml", fake_collect_full_scope_xml)
    monkeypatch.setattr("test_report_plugin.run_report_generation", fake_run_report_generation)
    monkeypatch.setattr("test_report_plugin.upload_report_artifacts", fake_upload_report_artifacts)
    monkeypatch.setattr(
        "test_report_plugin.create_buildkite_annotation",
        lambda body, context, style, priority, scope: annotations.append(
            (body, context, style, priority, scope)
        ),
    )

    assert main() == 0
    assert annotations[0][1:] == ("test-report:full", "error", 10, "build")
    assert "No JUnit XML was found" in annotations[0][0]
    assert "No JUnit XML was found" in capsys.readouterr().err


def test_main_full_variant_annotation_context(monkeypatch, tmp_path):
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    (xml_dir / "test.xml").write_text("<testsuites />", encoding="utf-8")

    monkeypatch.setattr(
        "os.environ",
        {
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE": "Full Tests",
            "BUILDKITE_PIPELINE_SLUG": "project",
            "BUILDKITE_BUILD_ID": "build-1",
            "BUILDKITE_BRANCH": "main",
        },
    )

    from object_store import ObjectAuth, StoreConfig

    monkeypatch.setattr(
        "test_report_plugin.resolve_object_store_context",
        lambda: __import__(
            "test_report_plugin", fromlist=["ObjectStoreContext"]
        ).ObjectStoreContext(
            StoreConfig("s3", "s3://bucket/prefix", artifacts_domain="reports.example.com"),
            ObjectAuth(),
            "bucket",
            "prefix",
        ),
    )

    def fake_collect_full_scope_xml(**kwargs):
        from report_downloads import DownloadedJobXml, JobXmlObject

        staged = kwargs["output_dir"] / "linux" / "job-1" / "test.xml"
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text("<testsuites />", encoding="utf-8")
        return [
            DownloadedJobXml(
                object=JobXmlObject(
                    variant="linux",
                    job_id="job-1",
                    key="prefix/project/refs/heads/main/reports/builds/build-1/variants/linux/jobs/job-1/xml/test.xml",
                    relative_path="test.xml",
                    size_bytes=15,
                ),
                local_path=staged,
            )
        ]

    monkeypatch.setattr("test_report_plugin.collect_full_scope_xml", fake_collect_full_scope_xml)

    def fake_run_report_generation(config, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        html_path = output_dir / "index.html"
        summary_path = output_dir / "summary.json"
        html_path.write_text("html", encoding="utf-8")
        summary_path.write_text(
            '{"root_status":"SUCCESSFUL","logical_tests":0,"targets":1,"status_counts":{}}',
            encoding="utf-8",
        )
        return GenerationResult(html_path=html_path, summary_path=summary_path)

    def fake_upload_report_artifacts(config, generation, xml_uploads, store_context=None):
        from object_store import PublishedObject

        return {
            "html": PublishedObject(
                "bucket",
                "prefix/full/index.html",
                "https://reports.example.com/full/index.html",
                4,
            )
        }

    annotations = []
    monkeypatch.setattr("test_report_plugin.run_report_generation", fake_run_report_generation)
    monkeypatch.setattr("test_report_plugin.upload_report_artifacts", fake_upload_report_artifacts)
    monkeypatch.setattr(
        "test_report_plugin.create_buildkite_annotation",
        lambda body, context, style, priority, scope: annotations.append(
            (body, context, style, priority, scope)
        ),
    )

    assert main() == 0
    assert annotations == [(annotations[0][0], "test-report:full", "success", 10, "build")]


def test_main_full_scope_downloads_xml_from_object_store(monkeypatch, tmp_path):
    generated = tmp_path / "generated"
    source_path = tmp_path / "local-fallback"
    source_path.mkdir()
    (source_path / "fallback.xml").write_text("<testsuites />", encoding="utf-8")

    env = {
        "BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE": "Full Tests",
        "BUILDKITE_PLUGIN_QDB_TEST_REPORT_ANNOTATE": "false",
        "BUILDKITE_PIPELINE_SLUG": "project",
        "BUILDKITE_BUILD_ID": "build-1",
        "BUILDKITE_BRANCH": "main",
    }
    monkeypatch.setattr("os.environ", env)

    mock_s3 = MagicMock()
    mock_ssm = MagicMock()
    monkeypatch.setattr("test_report_plugin.aws_clients", lambda: (mock_s3, mock_ssm))

    from object_store import ObjectAuth, StoreConfig
    from report_downloads import DownloadedJobXml, JobXmlObject

    store_cfg = StoreConfig(
        backend="s3",
        destination="s3://bucket/prefix",
        artifacts_domain="reports.example.com",
    )
    auth = ObjectAuth()
    monkeypatch.setattr("test_report_plugin.load_store_config", lambda ssm: store_cfg)
    monkeypatch.setattr("test_report_plugin.resolve_object_auth", lambda *args, **kwargs: auth)

    staged_xml_paths = []

    def fake_collect_full_scope_xml(**kwargs):
        assert kwargs["bucket"] == "bucket"
        assert kwargs["destination_prefix"] == "prefix"
        assert kwargs["project_id"] == "project"
        assert kwargs["git_ref"] == "refs/heads/main"
        assert kwargs["build_id"] == "build-1"
        stage_root = kwargs["output_dir"]
        local_path = stage_root / "linux" / "job-1" / "results.xml"
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text("<testsuites />", encoding="utf-8")
        staged_xml_paths.append(local_path)
        return [
            DownloadedJobXml(
                object=JobXmlObject(
                    variant="linux",
                    job_id="job-1",
                    key="prefix/project/refs/heads/main/reports/variants/linux/builds/build-1/jobs/job-1/xml/results.xml",
                    relative_path="results.xml",
                    size_bytes=15,
                ),
                local_path=local_path,
            )
        ]

    monkeypatch.setattr("test_report_plugin.collect_full_scope_xml", fake_collect_full_scope_xml)

    captured = {}

    def fake_run_report_generation(config, output_dir, **kwargs):
        captured["platforms"] = [(p.name, p.path) for p in config.platforms]
        output_dir = generated
        output_dir.mkdir(parents=True, exist_ok=True)
        html_path = output_dir / "index.html"
        summary_path = output_dir / "summary.json"
        html_path.write_text("html", encoding="utf-8")
        summary_path.write_text(
            '{"root_status":"SUCCESSFUL","status_counts":{"SUCCESSFUL":1}}',
            encoding="utf-8",
        )
        return GenerationResult(html_path=html_path, summary_path=summary_path)

    uploaded_xml = []

    def fake_upload_report_artifacts(config, generation, xml_uploads, store_context=None):
        uploaded_xml.extend(xml_uploads)
        from object_store import PublishedObject

        return {
            "html": PublishedObject(
                "bucket",
                "prefix/full/index.html",
                "https://reports.example.com/full/index.html",
                4,
            )
        }

    monkeypatch.setattr("test_report_plugin.run_report_generation", fake_run_report_generation)
    monkeypatch.setattr("test_report_plugin.upload_report_artifacts", fake_upload_report_artifacts)

    exit_code = main()

    assert exit_code == 0
    assert captured["platforms"] == [("linux", staged_xml_paths[0].parent.parent)]
    assert [xml.object_relative_path for xml in uploaded_xml] == ["linux/job-1/results.xml"]


def test_main_aggregate_attaches_job_artifacts_to_source_not_root(monkeypatch):
    monkeypatch.setattr(
        "os.environ",
        {
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE": "Full Tests",
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_ANNOTATE": "false",
            "BUILDKITE_PIPELINE_SLUG": "project",
            "BUILDKITE_BUILD_ID": "build-1",
            "BUILDKITE_BRANCH": "main",
        },
    )

    from object_store import ObjectAuth, StoreConfig
    from report_downloads import DownloadedJobXml, JobXmlObject

    store_cfg = StoreConfig(
        backend="s3",
        destination="s3://bucket/prefix",
        artifacts_domain="reports.example.com",
    )
    monkeypatch.setattr(
        "test_report_plugin.resolve_object_store_context",
        lambda: __import__(
            "test_report_plugin", fromlist=["ObjectStoreContext"]
        ).ObjectStoreContext(store_cfg, ObjectAuth(), "bucket", "prefix"),
    )

    def fake_collect_full_scope_xml(**kwargs):
        local_path = kwargs["output_dir"] / "linux" / "job-1" / "results.xml"
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text("<testsuites />", encoding="utf-8")
        return [
            DownloadedJobXml(
                object=JobXmlObject(
                    variant="linux",
                    job_id="job-1",
                    key="prefix/project/refs/heads/main/reports/builds/build-1/variants/linux/jobs/job-1/xml/results.xml",
                    relative_path="results.xml",
                    size_bytes=15,
                ),
                local_path=local_path,
            )
        ]

    monkeypatch.setattr("test_report_plugin.collect_full_scope_xml", fake_collect_full_scope_xml)
    monkeypatch.setattr(
        "test_report_plugin.collect_full_scope_job_summaries",
        lambda **kwargs: {
            "job-1": {
                "variant": "linux",
                "job_id": "job-1",
                "artifacts": [
                    {
                        "name": "Test logs",
                        "input_path": "test-logs-*.tar.gz",
                        "files": [
                            {
                                "relative_path": "test-logs-1.tar.gz",
                                "key": "prefix/project/refs/heads/main/reports/builds/build-1/variants/linux/jobs/job-1/artifacts/test-logs/test-logs-1.tar.gz",
                                "url": "https://reports.example.com/prefix/project/refs/heads/main/reports/builds/build-1/variants/linux/jobs/job-1/artifacts/test-logs/test-logs-1.tar.gz",
                                "size_bytes": 4,
                            }
                        ],
                        "warnings": [],
                    }
                ],
            }
        },
    )

    captured = {}

    def fake_run_report_generation(config, output_dir, **kwargs):
        captured.update(kwargs)
        output_dir.mkdir(parents=True, exist_ok=True)
        html_path = output_dir / "index.html"
        summary_path = output_dir / "summary.json"
        html_path.write_text("html", encoding="utf-8")
        summary_path.write_text(
            '{"root_status":"SUCCESSFUL","status_counts":{"SUCCESSFUL":1}}',
            encoding="utf-8",
        )
        return GenerationResult(html_path=html_path, summary_path=summary_path)

    monkeypatch.setattr("test_report_plugin.run_report_generation", fake_run_report_generation)
    monkeypatch.setattr(
        "test_report_plugin.upload_report_artifacts",
        lambda config, generation, xml_uploads, store_context=None: {},
    )

    assert main() == 0
    assert captured["artifacts"] == []
    links_by_job = captured["source_artifacts_by_job_id"]
    assert list(links_by_job) == ["job-1"]
    assert links_by_job["job-1"][0].name == "Test logs"
    assert links_by_job["job-1"][0].relative_path == "test-logs-1.tar.gz"


def test_main_aggregate_renders_job_manifest_artifacts_in_html(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "os.environ",
        {
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE": "Full test report",
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_ANNOTATE": "false",
            "BUILDKITE_PIPELINE_SLUG": "quasardb-build",
            "BUILDKITE_BUILD_ID": "019edee4-9015-4e35-8327-3c6db7823db",
            "BUILDKITE_BRANCH": "sc-19176/buildkite-capture-logs-of-test-runner-in-test-report",
            "BUILDKITE_BUILD_URL": "https://buildkite.com/quasar-1/quasardb-build/builds/691",
        },
    )

    from object_store import ObjectAuth, StoreConfig, PublishedObject
    from report_downloads import collect_full_scope_job_summaries

    build_id = "019edee4-9015-4e35-8327-3c6db7823db"
    job_id = "019edee4-29d1-47ea-b9c8-c2f04c145ad8"
    variant = "windows-haswell-release"
    base_prefix = (
        "quasardb-build/refs/heads/sc-19176/"
        "buildkite-capture-logs-of-test-runner-in-test-report/"
        f"reports/builds/{build_id}/variants"
    )
    xml_key = (
        f"{base_prefix}/{variant}/jobs/{job_id}/xml/"
        "build/Release/test-reports/qdb_aggregation_test.xml"
    )
    summary_key = f"{base_prefix}/{variant}/jobs/{job_id}/summary.json"
    artifact_url = (
        f"https://cid-artifacts.quasar.ai/{base_prefix}/{variant}/jobs/{job_id}/"
        "artifacts/test-logs/test-logs-1781858440.tar.gz"
    )
    summary = {
        "artifacts": [
            {
                "name": "Test logs",
                "input_path": "test-logs-*.tar.gz",
                "files": [
                    {
                        "relative_path": "test-logs-1781858440.tar.gz",
                        "key": (
                            f"{base_prefix}/{variant}/jobs/{job_id}/"
                            "artifacts/test-logs/test-logs-1781858440.tar.gz"
                        ),
                        "url": artifact_url,
                        "size_bytes": 123,
                    }
                ],
                "warnings": [],
            }
        ]
    }
    xml = (
        '<testsuites><testsuite name="qdb_unit_tests">'
        '<testcase classname="aggregation.correlation" '
        'name="double_identical_high_covariance" time="0"/>'
        "</testsuite></testsuites>"
    )

    class FakeObject:
        def __init__(self, key, size_bytes):
            self.key = key
            self.size_bytes = size_bytes

    def fake_list_objects(cfg, auth, bucket, prefix):
        assert prefix == base_prefix
        return [
            FakeObject(xml_key, len(xml)),
            FakeObject(summary_key, len(json.dumps(summary))),
        ]

    def fake_download_file(cfg, auth, bucket, key, local_path, **kwargs):
        local_path.parent.mkdir(parents=True, exist_ok=True)
        if key == xml_key:
            local_path.write_text(xml, encoding="utf-8")
        elif key == summary_key:
            local_path.write_text(json.dumps(summary), encoding="utf-8")
        else:  # pragma: no cover - guard for unexpected object-store access
            raise AssertionError(key)

    monkeypatch.setattr("report_downloads.list_objects", fake_list_objects)
    monkeypatch.setattr("report_downloads.download_file", fake_download_file)
    monkeypatch.setattr(
        "test_report_plugin.collect_full_scope_job_summaries",
        collect_full_scope_job_summaries,
    )
    monkeypatch.setattr(
        "test_report_plugin.resolve_object_store_context",
        lambda: ObjectStoreContext(
            StoreConfig(
                backend="s3",
                destination="s3://bucket",
                artifacts_domain="cid-artifacts.quasar.ai",
            ),
            ObjectAuth(),
            "bucket",
            "",
        ),
    )

    uploaded_html = tmp_path / "aggregate-index.html"

    def fake_upload_file(cfg, auth, bucket, key, local_path, **kwargs):
        if key.endswith("/full/index.html"):
            uploaded_html.write_text(local_path.read_text(encoding="utf-8"), encoding="utf-8")
        return PublishedObject(
            bucket=bucket,
            key=key,
            url=f"https://cid-artifacts.quasar.ai/{key}",
            size_bytes=local_path.stat().st_size,
        )

    monkeypatch.setattr("test_report_plugin.upload_file", fake_upload_file)

    assert main() == 0
    html = uploaded_html.read_text(encoding="utf-8")
    assert "sourceArtifacts" in html
    assert "Test logs" in html
    assert artifact_url in html
    match = re.search(
        r'<script id="report-data" type="application/json">(.*?)</script>', html, re.S
    )
    assert match is not None
    data = json.loads(match.group(1))
    node_names = [node["name"] for node in data[0]["testNodes"]]
    assert "qdb_aggregation_test" in node_names
    assert "aggregation.correlation" in node_names
    assert "double_identical_high_covariance" in node_names
