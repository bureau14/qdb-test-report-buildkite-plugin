from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from object_store import key_join


@dataclass(frozen=True)
class ReportLocation:
    base_prefix: str
    html_key: str
    summary_key: str
    xml_prefix: str
    artifact_prefix: str


def build_report_location(
    *,
    destination_prefix: str,
    project_id: str,
    git_ref: str,
    build_id: str,
    scope: str,
    job_id: str | None,
    variant: str | None = None,
) -> ReportLocation:
    # Base parts: <prefix>/<project_id>/<git_ref>/reports/builds/<build_id>
    parts = [destination_prefix, project_id, git_ref, "reports", "builds", build_id]

    if scope == "job":
        if not variant:
            raise ValueError("job scope requires variant")
        if not job_id:
            raise ValueError("job scope requires BUILDKITE_JOB_ID")
        parts.extend(["variants", variant, "jobs", job_id])
    else:
        parts.append("full")

    base_prefix = key_join(*parts)

    return ReportLocation(
        base_prefix=base_prefix,
        html_key=key_join(base_prefix, "index.html"),
        summary_key=key_join(base_prefix, "summary.json"),
        xml_prefix=key_join(base_prefix, "xml"),
        artifact_prefix=key_join(base_prefix, "artifacts"),
    )


def build_ctest_cost_data_discovery_prefix(
    *, destination_prefix: str, project_id: str, git_ref: str, variant: str, step_key: str
) -> str:
    return (
        key_join(
            destination_prefix,
            project_id,
            git_ref,
            "reports/ctest-cost/v1",
            quote(variant, safe=""),
            quote(step_key, safe=""),
        )
        + "/"
    )


def build_ctest_cost_data_descriptor_key(
    *,
    destination_prefix: str,
    project_id: str,
    git_ref: str,
    variant: str,
    step_key: str,
    build_number: int,
    job_id: str,
) -> str:
    return key_join(
        build_ctest_cost_data_discovery_prefix(
            destination_prefix=destination_prefix,
            project_id=project_id,
            git_ref=git_ref,
            variant=variant,
            step_key=step_key,
        ),
        str(build_number),
        quote(job_id, safe="") + ".json",
    )
