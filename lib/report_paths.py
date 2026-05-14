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


def report_scope_key(scope: str, job_id: Optional[str]) -> str:
    if scope == "full":
        return "full"
    if scope == "job":
        if not job_id:
            raise ValueError("job scope requires BUILDKITE_JOB_ID")
        return key_join("jobs", job_id)
    raise ValueError(f"unsupported report scope: {scope}")


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
    if scope == "job" and not variant:
        raise ValueError("job scope requires variant")

    # Base parts: <prefix>/<project_id>/<git_ref>/reports
    parts = [destination_prefix, project_id, git_ref, "reports"]
    
    if variant:
        parts.extend(["variants", variant])
        
    parts.extend(["builds", build_id])
    
    scope_key = report_scope_key(scope, job_id)
    parts.append(scope_key)
    
    base_prefix = key_join(*parts)
    
    return ReportLocation(
        base_prefix=base_prefix,
        html_key=key_join(base_prefix, "index.html"),
        summary_key=key_join(base_prefix, "summary.json"),
        xml_prefix=key_join(base_prefix, "xml")
    )
