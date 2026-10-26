"""Publish cumulative job runtime and agent wait from an aggregate report."""

from __future__ import annotations

import html
import json
import os
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
    rows = []
    finishes = []
    incomplete = 0
    for job in jobs:
        started = timestamp(job.get("started_at"))
        finished = timestamp(job.get("finished_at"))
        runnable = timestamp(job.get("runnable_at"))
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
        if started is None and runnable is None:
            continue
        runtime = duration(started, finished)
        # A canceled job can spend time in the agent queue without ever starting.
        wait = duration(runnable, started or finished)
        name = job.get("name") or job.get("step_key") or job["id"]
        name = html.escape(name).replace("|", "\\|").replace("\n", " ").replace("\r", " ")
        if job.get("retried"):
            name += " (retried)"
        rows.append((name, runtime, wait))

    total_runtime = sum(runtime for _, runtime, _ in rows if runtime is not None)
    total_wait = sum(wait for _, _, wait in rows if wait is not None)
    elapsed = duration(timestamp(build.get("created_at")), max(finishes) if finishes else None)
    lines = [
        "### Build timing — excluding test report",
        "",
        (
            f"**Total runtime: {format_duration(total_runtime)} · "
            f"Total agent wait: {format_duration(total_wait)}**"
        ),
        "",
        f"Elapsed: {format_duration(elapsed)}",
        "",
        "| Job | Runtime | Agent wait |",
        "|---|---:|---:|",
    ]
    for name, runtime, wait in sorted(rows, key=lambda row: row[1] or 0, reverse=True):
        lines.append(f"| {name} | {format_duration(runtime)} | {format_duration(wait)} |")
    lines.extend(
        [
            (
                f"| **Total** | **{format_duration(total_runtime)}** | "
                f"**{format_duration(total_wait)}** |"
            ),
            "",
            (
                "*Totals sum across job attempts, including retries. Parallel execution means "
                "they can exceed elapsed time. Agent wait excludes dependency wait.*"
            ),
        ]
    )
    if any(runtime is None or wait is None for _, runtime, wait in rows):
        lines.extend(["", "Unavailable timings are shown as — and excluded from totals."])
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
