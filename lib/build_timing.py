"""Publish build and test runtimes grouped by platform and variant."""

from __future__ import annotations

import html
import json
import os
import re
from collections import defaultdict
from datetime import datetime
from urllib.parse import quote
from urllib.request import Request, urlopen

from annotations import create_buildkite_annotation
from botocore.exceptions import BotoCoreError, ClientError
from object_store import aws_clients
from report_logging import logger

TOKEN_SSM_PARAMETER = "/services/buildkite/credentials/bk-time-annotations"


def timestamp(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def duration(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return max(0.0, (end - start).total_seconds())


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    hours, remainder = divmod(round(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or hours:
        parts.append(f"{minutes:02d}m")
    parts.append(f"{seconds:02d}s")
    return " ".join(parts)


def get_api_token() -> str:
    _, ssm = aws_clients()
    response = ssm.get_parameter(Name=TOKEN_SSM_PARAMETER, WithDecryption=True)
    token = response["Parameter"]["Value"]
    if not isinstance(token, str) or not token.strip():
        raise ValueError(f"SSM parameter {TOKEN_SSM_PARAMETER} contains no API token.")
    return token.strip()


def fetch_build() -> dict:
    token = get_api_token()
    parts = [
        quote(os.environ[name], safe="")
        for name in (
            "BUILDKITE_ORGANIZATION_SLUG",
            "BUILDKITE_PIPELINE_SLUG",
            "BUILDKITE_BUILD_NUMBER",
        )
    ]
    url = (
        f"https://api.buildkite.com/v2/organizations/{parts[0]}"
        f"/pipelines/{parts[1]}/builds/{parts[2]}?include_retried_jobs=true"
    )
    request = Request(url, headers={"Authorization": f"Bearer {token}"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def render_runtime_table(title: str, groups: dict) -> list[str]:
    lines = [
        f"**{title}**",
        "",
        "| "
        + ("Platform" if title == "Platform summary" else "Variant")
        + " | Build | Tests | Total |",
        "|---|---:|---:|---:|",
    ]
    for name, (build_time, test_time) in sorted(
        groups.items(), key=lambda item: sum(item[1]), reverse=True
    ):
        name = html.escape(name).replace("|", "&#124;").replace("\\", "&#92;")
        lines.append(
            f"| {name} | {format_duration(build_time)} | {format_duration(test_time)} | "
            f"{format_duration(build_time + test_time)} |"
        )
    return lines


def render_summary(build: dict) -> str:
    jobs = [
        job
        for job in build["jobs"]
        if job["type"] == "script"
        and (
            not os.environ.get("BUILDKITE_STEP_KEY")
            or job.get("step_key") != os.environ["BUILDKITE_STEP_KEY"]
        )
        and job.get("id") != os.environ.get("BUILDKITE_JOB_ID")
    ]
    variants = defaultdict(lambda: [0.0, 0.0])
    platforms = defaultdict(lambda: [0.0, 0.0])
    finishes = []
    incomplete = 0
    missing = 0
    other_time = 0.0
    for job in jobs:
        started = timestamp(job.get("started_at"))
        finished = timestamp(job.get("finished_at"))
        if finished is None:
            if job.get("state") not in {
                "skipped",
                "broken",
                "not_run",
                "waiting_failed",
                "blocked_failed",
                "unblocked_failed",
            }:
                incomplete += 1
            continue
        finishes.append(finished)
        runtime = duration(started, finished)
        if runtime is None:
            if job.get("state") in {"passed", "failed", "timed_out"}:
                missing += 1
            continue
        # QuasarDB labels preserve the same variant across build, regular test,
        # parallel test, and protocol-compatibility steps.
        match = re.fullmatch(r"(build|test)(?: - [^(]+)? \(([^)]+)\)", job.get("name") or "")
        if match is None:
            other_time += runtime
            continue
        stage, variant = match.groups()
        column = 0 if stage == "build" else 1
        platform = variant.split("-", 1)[0]
        platform = {
            "linux": "Linux",
            "freebsd": "FreeBSD",
            "windows": "Windows",
            "macos": "macOS",
        }.get(platform, platform)
        variants[variant][column] += runtime
        platforms[platform][column] += runtime

    build_time = sum(times[0] for times in variants.values())
    test_time = sum(times[1] for times in variants.values())
    total_runtime = build_time + test_time + other_time
    elapsed = duration(timestamp(build.get("created_at")), max(finishes) if finishes else None)
    lines = [
        "### Build timing",
        "",
        (
            f"**Build runtime: {format_duration(build_time)} · "
            f"Test runtime: {format_duration(test_time)} · "
            f"Total runtime: {format_duration(total_runtime)}**"
        ),
        "",
        f"Build and tests elapsed: {format_duration(elapsed)}",
    ]
    if other_time:
        lines.extend(
            ["", f"Other jobs: {format_duration(other_time)} (included in total runtime)."]
        )
    if variants:
        lines.extend(["", *render_runtime_table("Platform summary", platforms)])
        lines.extend(["", *render_runtime_table("Variant totals", variants)])
    lines.extend(
        [
            "",
            (
                "*Runtimes sum across job attempts, including retries. Parallel execution means "
                "totals can exceed elapsed time. Report step excluded; durations rounded independently.*"
            ),
        ]
    )
    if missing:
        lines.extend(["", f"Runtime unavailable for {missing} job(s); excluded from totals."])
    if incomplete:
        lines.extend(["", f"Partial summary: {incomplete} unfinished job(s) excluded."])
    return "\n".join(lines)


def publish_build_timing() -> None:
    try:
        body = render_summary(fetch_build())
    except (BotoCoreError, ClientError, OSError, KeyError, ValueError) as error:
        # API/SSM failures must not prevent test reports from being published.
        message = f"Build timing summary unavailable: {error}"
        logger.warning(message)
        body = f"### Build timing\n\n{html.escape(message)}"
        style = "warning"
    else:
        style = "info"
    try:
        create_buildkite_annotation(body, "build-timing", style, priority=10, scope="build")
    except OSError as error:
        logger.warning(f"Unable to publish build timing annotation: {error}")
