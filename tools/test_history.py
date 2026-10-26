#!/usr/bin/env python3
"""Fetch completed Buildkite builds and analyze their stored JUnit history."""

from __future__ import annotations

import argparse
import html
import json
import os
import statistics
import sys
import tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from junit_report_model import parse_junit_file
from object_store import ObjectAuth, StoreConfig, parse_s3
from report_downloads import collect_full_scope_xml


def fetch_builds(organization, pipeline, branch, count, token, opener=urlopen):
    """Return newest N finished builds, including failures, using build UUIDs."""
    if count < 1:
        raise ValueError("build count must be positive")
    base = "https://api.buildkite.com/v2/organizations/{}/pipelines/{}/builds".format(
        quote(organization, safe=""), quote(pipeline, safe="")
    )
    builds = []
    seen = set()
    page = 1
    while len(builds) < count:
        query = urlencode(
            {
                "branch": branch,
                "per_page": 100,
                "page": page,
                "exclude_jobs": "true",
                "exclude_pipeline": "true",
            }
        )
        request = Request(base + "?" + query, headers={"Authorization": "Bearer " + token})
        with opener(request, timeout=60) as response:
            batch = json.load(response)
        if not batch:
            break
        for build in batch:
            if (
                build.get("branch") == branch
                and build.get("finished_at")
                and build["id"] not in seen
            ):
                seen.add(build["id"])
                builds.append(
                    {
                        key: build.get(key)
                        for key in (
                            "id",
                            "number",
                            "branch",
                            "state",
                            "commit",
                            "web_url",
                            "created_at",
                            "finished_at",
                        )
                    }
                )
                if len(builds) == count:
                    break
        page += 1
    return builds


def collect_snapshot(build, branch, destination, project, directory):
    bucket, prefix = parse_s3(destination)
    errors = []
    files = collect_full_scope_xml(
        cfg=StoreConfig(backend="s3", destination=destination),
        auth=ObjectAuth(),
        bucket=bucket,
        destination_prefix=prefix,
        project_id=project,
        git_ref="refs/heads/" + branch,
        build_id=build["id"],
        output_dir=directory,
        archive_errors=errors,
    )
    observations = {}
    for item in files:
        malformed = []
        executions = parse_junit_file(
            item.local_path,
            item.variant,
            source_id=item.relative_path,
            source_job_id=item.job_id,
            malformed_junit_xml=malformed,
        )
        errors.extend(malformed)
        if not executions and not malformed:
            errors.append(
                {
                    "file": item.relative_path,
                    "job_id": item.job_id,
                    "error": "No testcases (empty or unsupported report)",
                }
            )
        for execution in executions:
            # Relative report paths distinguish suites with identical testcase names;
            # build UUIDs, job UUIDs and execution IDs never enter the identity.
            key = (
                item.variant,
                item.relative_path,
                execution.suite_name,
                execution.classname,
                execution.name,
            )
            observation = observations.setdefault(
                key, {"statuses": set(), "durations": [], "jobs": set(), "reasons": set()}
            )
            observation["statuses"].add(execution.status)
            if execution.status == "SUCCESSFUL":
                observation["durations"].append(execution.duration_seconds)
            observation["jobs"].add(item.job_id)
            if execution.reason:
                observation["reasons"].add(execution.reason[:500])
    tests = []
    for key, observation in sorted(observations.items()):
        tests.append(
            {
                "identity": list(key),
                "statuses": sorted(observation["statuses"]),
                "duration": statistics.median(observation["durations"])
                if observation["durations"]
                else None,
                "jobs": sorted(observation["jobs"]),
                "reasons": sorted(observation["reasons"]),
            }
        )
    return {"build": build, "xml_files": len(files), "errors": errors, "tests": tests}


def outcome(observation):
    if observation is None:
        return "MISSING"
    statuses = set(observation["statuses"])
    if statuses & {"FAILED", "ERRORED"}:
        return "FAILED"
    if "SUCCESSFUL" in statuses:
        return "PASSED"
    return "SKIPPED"


def analyze(snapshots):
    """Analyze oldest-to-newest snapshots; gaps never count as passes."""
    indexes = [{tuple(test["identity"]): test for test in s["tests"]} for s in snapshots]
    identities = sorted({key for index in indexes for key in index})
    rows = []
    for key in identities:
        observations = [index.get(key) for index in indexes]
        states = [outcome(item) for item in observations]
        measured = [state for state in states if state in {"PASSED", "FAILED"}]
        transitions = sum(a != b for a, b in zip(measured, measured[1:]))
        mixed = any(
            item
            and "SUCCESSFUL" in item["statuses"]
            and set(item["statuses"]) & {"FAILED", "ERRORED"}
            for item in observations
        )
        latest = states[-1]
        start = len(states) - 1
        while start > 0 and states[start - 1] == "FAILED":
            start -= 1
        failed_since = snapshots[start]["build"] if latest == "FAILED" else None
        baseline = [
            item["duration"]
            for item in observations[:-1]
            if item and outcome(item) == "PASSED" and item["duration"] is not None
        ]
        median = statistics.median(baseline) if baseline else None
        duration = observations[-1]["duration"] if observations[-1] else None
        ratio = (
            duration / median
            if latest == "PASSED" and duration is not None and median and len(baseline) >= 3
            else None
        )
        previous = measured[:-1] if latest in {"PASSED", "FAILED"} else measured
        rows.append(
            {
                "identity": list(key),
                "latest": latest,
                "timeline": states,
                "suspected_flaky": bool(mixed or transitions >= 2),
                "mixed_outcomes": bool(mixed),
                "transitions": transitions,
                "failed_since": failed_since,
                "failure_start_known": bool(
                    failed_since and start > 0 and states[start - 1] == "PASSED"
                ),
                "failure_streak": len(states) - start if failed_since else 0,
                "new_failure": latest == "FAILED" and bool(previous) and previous[-1] == "PASSED",
                "resolved": latest == "PASSED" and bool(previous) and previous[-1] == "FAILED",
                "failed_builds": states.count("FAILED"),
                "measured_builds": len(measured),
                "failure_rate": states.count("FAILED") / len(measured) if measured else None,
                "missing_builds": states.count("MISSING"),
                "skipped_builds": states.count("SKIPPED"),
                "duration_seconds": duration,
                "baseline_seconds": median,
                "duration_ratio": ratio,
                "slowdown": ratio is not None and ratio >= 2,
                "latest_jobs": observations[-1]["jobs"] if observations[-1] else [],
                "latest_reasons": observations[-1]["reasons"] if observations[-1] else [],
            }
        )
    rows.sort(
        key=lambda row: (
            row["latest"] != "FAILED",
            not row["suspected_flaky"],
            -row["failed_builds"],
            row["identity"],
        )
    )
    return {
        "builds": [
            {"build": s["build"], "xml_files": s["xml_files"], "errors": s["errors"]}
            for s in snapshots
        ],
        "summary": dict(
            Counter(
                flag
                for row in rows
                for flag in ("suspected_flaky", "new_failure", "resolved", "slowdown")
                if row[flag]
            )
        ),
        "tests": rows,
    }


def render_history(data):
    escape = lambda value: html.escape(str(value), quote=True)
    rows = []
    builds = data["builds"]
    for test in data["tests"]:
        flags = ", ".join(
            flag.replace("_", " ")
            for flag in ("suspected_flaky", "new_failure", "resolved", "slowdown")
            if test[flag]
        )
        timeline = []
        for state, build in zip(test["timeline"], builds):
            metadata = build["build"]
            url = metadata.get("web_url") or ""
            if not url.startswith("https://"):
                url = "#"
            timeline.append(
                '<a class="{}" href="{}" title="Build #{}: {}">{}</a>'.format(
                    state,
                    escape(url),
                    escape(metadata["number"]),
                    state,
                    {"PASSED": "P", "FAILED": "F", "SKIPPED": "S", "MISSING": "?"}[state],
                )
            )
        since = test["failed_since"]
        cells = [
            " / ".join(test["identity"]),
            test["latest"],
            flags,
            "{}/{}".format(test["failed_builds"], test["measured_builds"]),
            (
                "#{}{}".format(
                    since["number"],
                    "" if test["failure_start_known"] else " (at least; boundary unknown)",
                )
            )
            if since
            else "",
            test["failure_streak"],
            "{:.2f}x".format(test["duration_ratio"]) if test["duration_ratio"] else "",
            "; ".join(test["latest_reasons"]),
        ]
        rows.append(
            "<tr>"
            + "".join("<td>" + escape(cell) + "</td>" for cell in cells)
            + '<td class="timeline">'
            + " ".join(timeline)
            + "</td></tr>"
        )
    coverage = "".join(
        "<li>Build #{}: {} XML files; {} report errors</li>".format(
            escape(item["build"]["number"]), item["xml_files"], len(item["errors"])
        )
        for item in builds
    )
    return (
        """<!doctype html><html lang="en"><meta charset="utf-8">
<title>Test history</title><style>
body{font:14px system-ui;margin:24px;color:#17233b;background:#f6f8fc}
table{border-collapse:collapse;background:white}td,th{padding:8px;border:1px solid #dde3ed;
text-align:left;vertical-align:top}th{position:sticky;top:0;background:#e8eef8}
.timeline{white-space:nowrap}a{padding:3px;text-decoration:none}
.FAILED{background:#ffcece}.PASSED{background:#cff2d6}.SKIPPED,.MISSING{background:#eee}
input{padding:8px;width:360px;margin:12px 0}</style>
<h1>Test history</h1><p>Oldest to newest. P = pass, F = failure/error, S = skipped,
? = missing. Click a timeline entry to open its build.</p>
<p>Suspected flaky = at least two pass/fail transitions among observed outcomes,
or mixed pass/fail results in one build. This is evidence of instability, not proof of flakiness.
Resolved/new failure compare the latest build with the previous measured outcome.
Failure streaks stop at missing/skipped builds. Slowdown = at least 2x the median of
at least three earlier passing builds. Missing reports are never passes.</p>
<details><summary>Report coverage</summary><ul>"""
        + coverage
        + """</ul></details>
<label>Filter tests <input id="filter" placeholder="Test, platform, or signal"></label>
<table><thead><tr>"""
        + "".join(
            "<th>" + title + "</th>"
            for title in (
                "Platform / report / suite / class / test",
                "Latest",
                "Signals",
                "Failed / measured",
                "Failed since",
                "Failure streak",
                "Duration / baseline",
                "Latest reason",
                "History",
            )
        )
        + "</tr></thead><tbody>"
        + "".join(rows)
        + """</tbody></table>
<script>document.getElementById('filter').addEventListener('input',event=>{
const query=event.target.value.toLowerCase();document.querySelectorAll('tbody tr').forEach(
row=>{row.hidden=!row.textContent.toLowerCase().includes(query)});});</script></html>"""
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organization", default="quasardb")
    parser.add_argument("--pipeline", default="quasardb-build")
    parser.add_argument("--branch", default="master")
    parser.add_argument("--builds", type=int, default=30)
    parser.add_argument("--destination", default="s3://qdb-cicd-artifacts")
    parser.add_argument("--project", default="quasardb-build")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    token = os.environ.get("BUILDKITE_API_TOKEN")
    if not token:
        parser.error("set BUILDKITE_API_TOKEN with read_builds permission")
    if args.builds < 1:
        parser.error("--builds must be positive")
    builds = fetch_builds(args.organization, args.pipeline, args.branch, args.builds, token)
    if not builds:
        parser.error("no completed builds found for this branch")
    snapshots = []
    for build in reversed(builds):
        print("Collecting build #{} ({})".format(build["number"], build["id"]), file=sys.stderr)
        with tempfile.TemporaryDirectory(prefix="test-history-") as directory:
            snapshots.append(
                collect_snapshot(
                    build, args.branch, args.destination, args.project, Path(directory)
                )
            )
    data = analyze(snapshots)
    data["branch"] = args.branch
    data["requested_builds"] = args.builds
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "history.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    (args.output / "history.html").write_text(render_history(data), encoding="utf-8")


if __name__ == "__main__":
    main()
