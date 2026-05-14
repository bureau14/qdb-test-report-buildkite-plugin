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


def _get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.environ.get(key, default)


def _get_bool_env(key: str, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.lower() in ("true", "on", "1")


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
    # Required properties
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
        raise ValueError(
            "missing required config: platforms (at least one platform is required)"
        )

    # Optional/Defaulted properties
    variant = _get_env("BUILDKITE_PLUGIN_QDB_TEST_REPORT_VARIANT")
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

    git_ref = resolve_buildkite_git_ref()

    only_failures = _get_bool_env(
        "BUILDKITE_PLUGIN_QDB_TEST_REPORT_ONLY_FAILURES", False
    )
    annotate = _get_bool_env("BUILDKITE_PLUGIN_QDB_TEST_REPORT_ANNOTATE", True)

    fail_on_test_failures = _get_bool_env(
        "BUILDKITE_PLUGIN_QDB_TEST_REPORT_FAIL_ON_TEST_FAILURES", scope == "job"
    )

    # Validation
    if scope == "job":
        if not variant:
            raise ValueError("scope=job requires variant")
        if not job_id:
            raise ValueError("scope=job requires BUILDKITE_JOB_ID")

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
    )
