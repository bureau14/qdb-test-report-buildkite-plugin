import json
import subprocess
import sys
from pathlib import Path

def build_annotation_body(title: str, summary: dict, html_url: str) -> str:
    """
    Builds the markdown body for the Buildkite annotation.
    """
    counts = summary.get("status_counts", {})
    failed = counts.get("FAILED", 0)
    errored = counts.get("ERRORED", 0)
    skipped = counts.get("SKIPPED", 0)
    
    # 31770 tests per target, 2 targets, 2 failed, 254 skipped
    # Adjust based on summary data
    logical_tests = summary.get("logical_tests", 0)
    targets = summary.get("targets", 1)
    
    parts = []
    if targets > 1:
        parts.append(f"{logical_tests} tests per target")
        parts.append(f"{targets} targets")
    else:
        parts.append(f"{logical_tests} tests")
        
    if failed > 0:
        parts.append(f"{failed} failed")
    if errored > 0:
        parts.append(f"{errored} errored")
    if skipped > 0:
        parts.append(f"{skipped} skipped")
        
    stats_line = ", ".join(parts)
    
    body = f"## {title}\n\n{stats_line}\n\n[Open HTML report]({html_url})"
    return body

def get_annotation_style(summary: dict) -> str:
    """
    Determines the annotation style (success, warning, error, info).
    """
    root_status = summary.get("root_status", "INFO")
    counts = summary.get("status_counts", {})
    failed = counts.get("FAILED", 0)
    errored = counts.get("ERRORED", 0)
    skipped = counts.get("SKIPPED", 0)
    
    if failed > 0 or errored > 0 or root_status in ("FAILED", "ERRORED"):
        return "error"
    if skipped > 0:
        return "warning"
    if root_status == "SUCCESSFUL":
        return "success"
    return "info"

def create_buildkite_annotation(
    body: str,
    context: str,
    style: str,
    priority: int,
    scope: str = "build"
):
    """
    Calls buildkite-agent annotate to create the annotation.
    """
    args = [
        "buildkite-agent", "annotate", body,
        "--context", context,
        "--style", style,
        "--priority", str(priority),
    ]
    if scope == "job":
        args.append("--scope")
        args.append("job")
        
    try:
        subprocess.run(args, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"WARNING: failed to create Buildkite annotation: {exc}", file=sys.stderr)
