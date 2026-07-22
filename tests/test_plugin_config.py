import pytest
from pathlib import Path
from plugin_config import ArtifactConfig, load_plugin_config, PlatformConfig


@pytest.fixture(autouse=True)
def bk_env(monkeypatch):
    monkeypatch.setenv("BUILDKITE_PIPELINE_SLUG", "my-pipeline")
    monkeypatch.setenv("BUILDKITE_BUILD_ID", "build-123")
    monkeypatch.setenv("BUILDKITE_BRANCH", "main")


def test_load_plugin_config_job_block_minimal(monkeypatch):
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE", "My Report")
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_VARIANT", "linux-x64")
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_JUNIT_INPUT_PATH", "reports/junit")
    monkeypatch.setenv("BUILDKITE_JOB_ID", "job-id-456")
    monkeypatch.setenv("BUILDKITE_BUILD_URL", "https://buildkite.com/build-123")
    monkeypatch.setenv("BUILDKITE_COMMIT", "0123456789abcdef0123456789abcdef01234567")
    monkeypatch.setenv("BUILDKITE_REPO", "https://github.com/acme/project.git")

    cfg = load_plugin_config()

    assert cfg.scope == "job"
    assert cfg.title == "My Report"
    assert cfg.variant == "linux-x64"
    assert cfg.junit_input_path == Path("reports/junit")
    assert cfg.platforms == [PlatformConfig(name="linux-x64", path=Path("reports/junit"))]
    assert cfg.project_id == "my-pipeline"
    assert cfg.git_ref == "refs/heads/main"
    assert cfg.build_id == "build-123"
    assert cfg.job_id == "job-id-456"
    assert cfg.build_url == "https://buildkite.com/build-123"
    assert cfg.commit == "0123456789abcdef0123456789abcdef01234567"
    assert cfg.repo == "https://github.com/acme/project.git"
    assert cfg.annotate is True
    assert cfg.fail_on_test_failures is True
    assert cfg.artifacts == []


def test_load_plugin_config_job_artifacts(monkeypatch):
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE", "My Report")
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_VARIANT", "linux-x64")
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_JUNIT_INPUT_PATH", "reports/junit")
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_ARTIFACTS_0_NAME", "Test logs")
    monkeypatch.setenv(
        "BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_ARTIFACTS_0_INPUT_PATH", "test-logs-*.tar.gz"
    )
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_ARTIFACTS_1_NAME", "Server logs")
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_ARTIFACTS_1_INPUT_PATH", "logs")
    monkeypatch.setenv("BUILDKITE_JOB_ID", "job-id-456")

    cfg = load_plugin_config()

    assert cfg.artifacts == [
        ArtifactConfig(name="Test logs", input_path=Path("test-logs-*.tar.gz")),
        ArtifactConfig(name="Server logs", input_path=Path("logs")),
    ]


def test_load_plugin_config_defaults_to_aggregate_when_no_job_block(monkeypatch):
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE", "Full Report")

    cfg = load_plugin_config()

    assert cfg.scope == "aggregate"
    assert cfg.fail_on_test_failures is False
    assert cfg.variant is None
    assert cfg.junit_input_path is None
    assert cfg.platforms == []
    assert cfg.commit is None
    assert cfg.repo is None
    assert cfg.aggregate_download_parallel == 32
    assert cfg.aggregate_download_concurrency == 4


def test_load_plugin_config_aggregate_download_options(monkeypatch):
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE", "Full Report")
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_AGGREGATE_DOWNLOAD_PARALLEL", "16")
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_AGGREGATE_DOWNLOAD_CONCURRENCY", "2")

    cfg = load_plugin_config()

    assert cfg.scope == "aggregate"
    assert cfg.aggregate_download_parallel == 16
    assert cfg.aggregate_download_concurrency == 2


def test_load_plugin_config_job_can_disable_fail_on_test_failures(monkeypatch):
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE", "Job Report")
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_VARIANT", "linux")
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_JUNIT_INPUT_PATH", "r1")
    monkeypatch.setenv("BUILDKITE_JOB_ID", "job-1")
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_FAIL_ON_TEST_FAILURES", "false")

    cfg = load_plugin_config()

    assert cfg.fail_on_test_failures is False


def test_load_plugin_config_common_options_are_top_level(monkeypatch):
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE", "T")
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_EXECUTION_NAME", "Execution")
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_PROJECT_ID", "project-x")
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_ONLY_FAILURES", "true")
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_ANNOTATE", "false")

    cfg = load_plugin_config()

    assert cfg.execution_name == "Execution"
    assert cfg.project_id == "project-x"
    assert cfg.only_failures is True
    assert cfg.annotate is False


def test_load_plugin_config_git_ref_tag(monkeypatch):
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE", "T")
    monkeypatch.setenv("BUILDKITE_TAG", "v1.2.3")
    monkeypatch.setenv("BUILDKITE_BRANCH", "main")

    cfg = load_plugin_config()
    assert cfg.git_ref == "refs/tags/v1.2.3"


def test_load_plugin_config_git_ref_missing(monkeypatch):
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE", "T")
    monkeypatch.delenv("BUILDKITE_TAG", raising=False)
    monkeypatch.delenv("BUILDKITE_BRANCH", raising=False)

    with pytest.raises(ValueError, match="missing Buildkite git ref"):
        load_plugin_config()


def test_load_plugin_config_missing_title(monkeypatch):
    with pytest.raises(ValueError, match="missing required config: title"):
        load_plugin_config()


def test_load_plugin_config_job_missing_variant(monkeypatch):
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE", "T")
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_JUNIT_INPUT_PATH", "p")
    monkeypatch.setenv("BUILDKITE_JOB_ID", "job-1")

    with pytest.raises(ValueError, match="job requires variant"):
        load_plugin_config()


def test_load_plugin_config_job_missing_junit_input_path(monkeypatch):
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE", "T")
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_VARIANT", "v")
    monkeypatch.setenv("BUILDKITE_JOB_ID", "job-1")

    with pytest.raises(ValueError, match="job requires junit_input_path"):
        load_plugin_config()


def test_load_plugin_config_job_missing_job_id(monkeypatch):
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE", "T")
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_VARIANT", "v")
    monkeypatch.setenv("BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_JUNIT_INPUT_PATH", "p")
    monkeypatch.delenv("BUILDKITE_JOB_ID", raising=False)

    with pytest.raises(ValueError, match="job requires BUILDKITE_JOB_ID"):
        load_plugin_config()
