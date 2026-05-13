import sys
import io
import json
import os
from pathlib import Path
from dataclasses import dataclass
from contextlib import redirect_stderr

# Add tools to path so we can import junit_html_report
tools_path = str(Path(__file__).parent.parent / "tools")
if tools_path not in sys.path:
    sys.path.append(tools_path)

import junit_html_report

from .plugin_config import PluginConfig, load_plugin_config
from .report_paths import build_report_location, ReportLocation
from .object_store import (
    load_store_config,
    resolve_object_auth,
    upload_file,
    parse_s3,
    aws_clients,
    key_join,
    PublishedObject,
)
from .xml_inputs import collect_xml_uploads, XmlUpload
from .annotations import build_annotation_body, get_annotation_style, create_buildkite_annotation

@dataclass(frozen=True)
class GenerationResult:
    html_path: Path
    summary_path: Path
    log_path: Path

def run_report_generation(config: PluginConfig, output_dir: Path) -> GenerationResult:
    """
    Runs the HTML report generator and returns the paths to the generated files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    html_path = output_dir / "index.html"
    summary_path = output_dir / "summary.json"
    log_path = output_dir / "generation.log"
    
    argv = [
        "--title", config.title,
        "--output", str(html_path),
        "--summary-json", str(summary_path),
        "--fail-on-status", "never",
    ]
    
    for p in config.platforms:
        argv.extend(["--platform", f"{p.name}={p.path}"])
        
    if config.execution_name:
        argv.extend(["--execution-name", config.execution_name])
    if config.build_url:
        argv.extend(["--build-url", config.build_url])
    if config.commit:
        argv.extend(["--commit", config.commit])
    if config.branch:
        argv.extend(["--branch", config.branch])
    if config.only_failures:
        argv.append("--only-failures")
        
    log_stream = io.StringIO()
    with redirect_stderr(log_stream):
        exit_code = junit_html_report.main(argv)
        
    log_content = log_stream.getvalue()
    log_path.write_text(log_content)
    
    if exit_code != 0:
        # If exit_code is non-zero even with --fail-on-status never, something is wrong.
        raise RuntimeError(f"Report generation failed with exit code {exit_code}. Logs:\n{log_content}")
        
    return GenerationResult(
        html_path=html_path,
        summary_path=summary_path,
        log_path=log_path,
    )

def upload_report_artifacts(
    config: PluginConfig,
    generation: GenerationResult,
    xml_uploads: list[XmlUpload],
) -> dict[str, PublishedObject]:
    """
    Uploads all report artifacts (HTML, summary, log, XML) to the object store.
    """
    s3, ssm = aws_clients()
    store_cfg = load_store_config(ssm)
    auth = resolve_object_auth(ssm, store_cfg, "upload")
    
    bucket, prefix = parse_s3(store_cfg.destination)
    
    location = build_report_location(
        destination_prefix=prefix,
        project_id=config.project_id,
        git_ref=config.git_ref,
        report_id=config.report_id,
        build_id=config.build_id,
        scope=config.scope,
        job_id=config.job_id,
        variant=config.variant,
    )
    
    results = {}
    
    # HTML
    print(f"INFO  Uploading HTML report to s3://{bucket}/{location.html_key}", file=sys.stderr)
    results["html"] = upload_file(
        store_cfg, auth, bucket, location.html_key, generation.html_path,
        content_type="text/html; charset=utf-8",
        content_disposition="inline",
    )
    
    # Summary JSON
    print(f"INFO  Uploading summary JSON to s3://{bucket}/{location.summary_key}", file=sys.stderr)
    results["summary"] = upload_file(
        store_cfg, auth, bucket, location.summary_key, generation.summary_path,
        content_type="application/json",
        content_disposition="inline",
    )
    
    # Log
    print(f"INFO  Uploading generation log to s3://{bucket}/{location.log_key}", file=sys.stderr)
    results["log"] = upload_file(
        store_cfg, auth, bucket, location.log_key, generation.log_path,
        content_type="text/plain; charset=utf-8",
        content_disposition="inline",
    )
    
    # XMLs
    for xml in xml_uploads:
        key = key_join(location.xml_prefix, xml.object_relative_path)
        print(f"INFO  Uploading JUnit XML {xml.object_relative_path} to s3://{bucket}/{key}", file=sys.stderr)
        results[f"xml:{xml.object_relative_path}"] = upload_file(
            store_cfg, auth, bucket, key, xml.local_path,
            content_type="application/xml",
            content_disposition="attachment",
        )
        
    return results

def main():
    try:
        config = load_plugin_config()
        
        # Collect XMLs first to ensure they exist
        xml_uploads = collect_xml_uploads(config.platforms)
        
        # Create temp dir for generation
        # e.g. .buildkite-test-report/<report_id>/<scope>/<variant-or-full>/
        variant_or_full = config.variant if (config.scope == "job" or (config.scope == "full" and config.variant)) else "full"
        tmp_base = Path(".buildkite-test-report") / config.report_id / config.scope / variant_or_full
        
        # Generate report
        print(f"INFO  Generating {config.scope} report id={config.report_id}", file=sys.stderr)
        generation = run_report_generation(config, tmp_base)
        
        if config.dry_run:
            print("INFO  Dry run mode: generation complete. Skipping upload.", file=sys.stderr)
            summary = json.loads(generation.summary_path.read_text())
            body = build_annotation_body(config.title, summary, "http://dry-run-url")
            print(f"INFO  [dry-run] Annotation body:\n{body}", file=sys.stderr)
            return 0
            
        # Upload
        uploads = upload_report_artifacts(config, generation, xml_uploads)
        
        # Annotation
        if config.annotate:
            html_url = uploads["html"].url
            if not html_url:
                print("WARNING: HTML public URL unavailable (ARTIFACTS_DOMAIN not set); skipping annotation", file=sys.stderr)
            else:
                summary = json.loads(generation.summary_path.read_text())
                body = build_annotation_body(config.title, summary, html_url)
                style = get_annotation_style(summary)
                
                if config.scope == "job":
                    context = f"test-report:{config.report_id}:{config.variant}:{config.job_id}"
                    create_buildkite_annotation(body, context, style, priority=10, scope="job")
                else:
                    context = f"test-report:{config.report_id}:full"
                    create_buildkite_annotation(body, context, style, priority=20, scope="build")
        
        # Final status check (Task 10 logic)
        summary = json.loads(generation.summary_path.read_text())
        if config.fail_on_status != "never" and summary.get("root_status") == config.fail_on_status.upper():
            print(f"INFO  Report status {summary.get('root_status')} matches fail_on_status={config.fail_on_status}. Exiting 64.", file=sys.stderr)
            return 64
            
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
