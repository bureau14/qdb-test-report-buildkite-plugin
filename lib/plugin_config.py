import os
from dataclasses import dataclass, field
from pathlib import Path

@dataclass(frozen=True)
class PlatformConfig:
    name: str
    path: Path


@dataclass(frozen=True)
class PluginConfig:
    report_id: str
    scope: str
    title: str
    variant: str | None
    execution_name: str | None
    project_id: str
    git_ref: str
    build_id: str
    job_id: str | None
    build_url: str | None
    commit: str | None
    branch: str | None
    platforms: list[PlatformConfig]
    only_failures: bool
    upload_xml: bool
    annotate: bool
    fail_on_status: str
    dry_run: bool


def _get_env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


def _get_bool_env(key: str, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.lower() in ("true", "on", "1")


def load_plugin_config() -> PluginConfig:
    # Required properties
    report_id = _get_env("BUILDKITE_PLUGIN_QDB_TEST_REPORT_REPORT_ID")
    if not report_id:
        raise ValueError("missing required config: report_id")
        
    scope = _get_env("BUILDKITE_PLUGIN_QDB_TEST_REPORT_SCOPE")
    if not scope:
        raise ValueError("missing required config: scope")
    if scope not in ("job", "full"):
        raise ValueError(f"scope must be 'job' or 'full', got {scope!r}")
        
    title = _get_env("BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE")
    if not title:
        raise ValueError("missing required config: title")
        
    # Platforms
    platforms = []
    idx = 0
    while True:
        name = _get_env(f"BUILDKITE_PLUGIN_QDB_TEST_REPORT_PLATFORMS_{idx}_NAME")
        path = _get_env(f"BUILDKITE_PLUGIN_QDB_TEST_REPORT_PLATFORMS_{idx}_PATH")
        if not name or not path:
            break
        platforms.append(PlatformConfig(name=name, path=Path(path)))
        idx += 1
        
    if not platforms:
        raise ValueError("missing required config: platforms (at least one platform is required)")

    # Optional/Defaulted properties
    variant = _get_env("BUILDKITE_PLUGIN_QDB_TEST_REPORT_VARIANT")
    execution_name = _get_env("BUILDKITE_PLUGIN_QDB_TEST_REPORT_EXECUTION_NAME")
    
    project_id = _get_env("BUILDKITE_PLUGIN_QDB_TEST_REPORT_PROJECT_ID") or _get_env("BUILDKITE_PIPELINE_SLUG")
    if not project_id:
        raise ValueError("missing required config: project_id (BUILDKITE_PIPELINE_SLUG not set)")
        
    build_id = _get_env("BUILDKITE_BUILD_ID")
    if not build_id:
        raise ValueError("missing required config: build_id (BUILDKITE_BUILD_ID not set)")
        
    job_id = _get_env("BUILDKITE_JOB_ID")
    build_url = _get_env("BUILDKITE_BUILD_URL")
    commit = _get_env("BUILDKITE_COMMIT")
    branch = _get_env("BUILDKITE_BRANCH")
    
    git_ref = _get_env("BUILDKITE_PLUGIN_QDB_TEST_REPORT_GIT_REF")
    if not git_ref:
        if branch:
            git_ref = f"refs/heads/{branch}"
        else:
            raise ValueError("missing required config: git_ref (BUILDKITE_BRANCH and custom GIT_REF not set)")

    only_failures = _get_bool_env("BUILDKITE_PLUGIN_QDB_TEST_REPORT_ONLY_FAILURES", False)
    upload_xml = _get_bool_env("BUILDKITE_PLUGIN_QDB_TEST_REPORT_UPLOAD_XML", True)
    annotate = _get_bool_env("BUILDKITE_PLUGIN_QDB_TEST_REPORT_ANNOTATE", True)
    
    default_fail_on_status = "never" if scope == "job" else "failed"
    fail_on_status = _get_env("BUILDKITE_PLUGIN_QDB_TEST_REPORT_FAIL_ON_STATUS", default_fail_on_status)
    
    dry_run = _get_bool_env("BUILDKITE_PLUGIN_QDB_TEST_REPORT_DRY_RUN", False)

    # Validation
    if scope == "job":
        if not variant:
            raise ValueError("scope=job requires variant")
        if not job_id:
            raise ValueError("scope=job requires BUILDKITE_JOB_ID")

    return PluginConfig(
        report_id=report_id,
        scope=scope,
        title=title,
        variant=variant,
        execution_name=execution_name,
        project_id=project_id,
        git_ref=git_ref,
        build_id=build_id,
        job_id=job_id,
        build_url=build_url,
        commit=commit,
        branch=branch,
        platforms=platforms,
        only_failures=only_failures,
        upload_xml=upload_xml,
        annotate=annotate,
        fail_on_status=fail_on_status,
        dry_run=dry_run,
    )
