from __future__ import annotations
from typing import Optional
from dataclasses import dataclass
from object_store import key_join


@dataclass(frozen=True)
class ReportLocation:
    base_prefix: str
    html_key: str
    summary_key: str
    xml_prefix: str


def build_report_location(
    *,
    destination_prefix: str,
    project_id: str,
    git_ref: str,
    build_id: str,
    scope: str,
    job_id: Optional[str],
    variant: Optional[str] = None,
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
    )
