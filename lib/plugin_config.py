from __future__ import annotations
from typing import List, Optional
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PlatformConfig:
    name: str
    path: Path


@dataclass(frozen=True)
class PluginConfig:
    scope: str
    title: str
    variant: Optional[str]
    execution_name: Optional[str]
    project_id: str
    git_ref: str
    build_id: str
    job_id: Optional[str]
    build_url: Optional[str]
    platforms: List[PlatformConfig]
    only_failures: bool
    annotate: bool
    fail_on_test_failures: bool
    junit_reports_path: Optional[Path] = None
    variants: List[str] = field(default_factory=list)
    commit: Optional[str] = None
    repo: Optional[str] = None


def _get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.environ.get(key, default)


def _has_env_with_prefix(prefix: str) -> bool:
    env_prefix = f"{prefix}_"
    return any(key.startswith(env_prefix) for key in os.environ)


def _get_bool_env(key: str, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.lower() in ("true", "on", "1")


def _get_list_env(prefix: str) -> List[str]:
    values: List[str] = []
    idx = 0
    while True:
        value = _get_env(f"{prefix}_{idx}")
        if value is None:
            break
        if value:
            values.append(value)
        idx += 1
    return values


def resolve_buildkite_git_ref() -> str:
    tag = _get_env("BUILDKITE_TAG")
    if tag:
        return f"refs/tags/{tag}"
    branch = _get_env("BUILDKITE_BRANCH")
    if branch:
        return f"refs/heads/{branch}"
    raise ValueError(
        "missing Buildkite git ref: expected BUILDKITE_TAG or BUILDKITE_BRANCH"
    )


def load_plugin_config() -> PluginConfig:
    title = _get_env("BUILDKITE_PLUGIN_QDB_TEST_REPORT_TITLE")
    if not title:
        raise ValueError("missing required config: title")

    job_prefix = "BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB"
    aggregate_prefix = "BUILDKITE_PLUGIN_QDB_TEST_REPORT_AGGREGATE"
    has_job = _has_env_with_prefix(job_prefix)
    has_aggregate = _has_env_with_prefix(aggregate_prefix)
    if has_job == has_aggregate:
        raise ValueError("exactly one of job or aggregate must be configured")

    scope = "job" if has_job else "aggregate"

    execution_name = _get_env("BUILDKITE_PLUGIN_QDB_TEST_REPORT_EXECUTION_NAME")

    project_id = _get_env("BUILDKITE_PLUGIN_QDB_TEST_REPORT_PROJECT_ID") or _get_env(
        "BUILDKITE_PIPELINE_SLUG"
    )
    if not project_id:
        raise ValueError(
            "missing required config: project_id (BUILDKITE_PIPELINE_SLUG not set)"
        )

    build_id = _get_env("BUILDKITE_BUILD_ID")
    if not build_id:
        raise ValueError(
            "missing required config: build_id (BUILDKITE_BUILD_ID not set)"
        )

    job_id = _get_env("BUILDKITE_JOB_ID")
    build_url = _get_env("BUILDKITE_BUILD_URL")
    commit = _get_env("BUILDKITE_COMMIT")
    repo = _get_env("BUILDKITE_REPO")

    git_ref = resolve_buildkite_git_ref()

    only_failures = _get_bool_env(
        "BUILDKITE_PLUGIN_QDB_TEST_REPORT_ONLY_FAILURES", False
    )
    annotate = _get_bool_env("BUILDKITE_PLUGIN_QDB_TEST_REPORT_ANNOTATE", True)

    variant: Optional[str]
    variants: List[str]
    junit_reports_path: Optional[Path]
    fail_on_test_failures: bool

    if scope == "job":
        variant = _get_env("BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_VARIANT")
        variants = _get_list_env("BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_VARIANTS")
        junit_reports_path_raw = _get_env(
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_JUNIT_REPORTS_PATH"
        )
        junit_reports_path = (
            Path(junit_reports_path_raw) if junit_reports_path_raw else None
        )

        if variants:
            raise ValueError("variants is only valid under aggregate")
        if not variant:
            raise ValueError("job requires variant")
        if not junit_reports_path:
            raise ValueError("job requires junit_reports_path")
        if not job_id:
            raise ValueError("job requires BUILDKITE_JOB_ID")

        fail_on_test_failures = _get_bool_env(
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_JOB_FAIL_ON_TEST_FAILURES", True
        )
        platforms = [PlatformConfig(name=variant, path=junit_reports_path)]
    else:
        variant = _get_env("BUILDKITE_PLUGIN_QDB_TEST_REPORT_AGGREGATE_VARIANT")
        variants = _get_list_env("BUILDKITE_PLUGIN_QDB_TEST_REPORT_AGGREGATE_VARIANTS")
        junit_reports_path_raw = _get_env(
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_AGGREGATE_JUNIT_REPORTS_PATH"
        )
        junit_reports_path = (
            Path(junit_reports_path_raw) if junit_reports_path_raw else None
        )

        if junit_reports_path:
            raise ValueError("junit_reports_path is only valid under job")
        if (
            "BUILDKITE_PLUGIN_QDB_TEST_REPORT_AGGREGATE_FAIL_ON_TEST_FAILURES"
            in os.environ
        ):
            raise ValueError("fail_on_test_failures is only valid under job")
        if not variants:
            raise ValueError("aggregate requires variants")

        fail_on_test_failures = False
        platforms = [PlatformConfig(name=name, path=Path(name)) for name in variants]

    return PluginConfig(
        scope=scope,
        title=title,
        variant=variant,
        execution_name=execution_name,
        project_id=project_id,
        git_ref=git_ref,
        build_id=build_id,
        job_id=job_id,
        build_url=build_url,
        platforms=platforms,
        only_failures=only_failures,
        annotate=annotate,
        fail_on_test_failures=fail_on_test_failures,
        junit_reports_path=junit_reports_path,
        variants=variants,
        commit=commit,
        repo=repo,
    )
