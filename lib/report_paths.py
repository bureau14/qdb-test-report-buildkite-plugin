from dataclasses import dataclass
from object_store import key_join

@dataclass(frozen=True)
class ReportLocation:
    base_prefix: str
    html_key: str
    summary_key: str
    log_key: str
    xml_prefix: str


def report_scope_key(scope: str, job_id: str | None) -> str:
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
    report_id: str,
    build_id: str,
    scope: str,
    job_id: str | None,
    variant: str | None = None,
) -> ReportLocation:
    if scope == "job" and not variant:
        raise ValueError("job scope requires variant")

    # Base parts: <prefix>/<project_id>/<git_ref>/reports/<report_id>
    parts = [destination_prefix, project_id, git_ref, "reports", report_id]
    
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
        log_key=key_join(base_prefix, "generation.log"),
        xml_prefix=key_join(base_prefix, "xml")
    )
