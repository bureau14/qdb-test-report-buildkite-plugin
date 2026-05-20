from __future__ import annotations
from typing import Dict, List, Optional
import sys
import json
import tempfile
from pathlib import Path
from dataclasses import dataclass, replace

# Add tools to path so we can import junit_html_report tool
tools_path = str(Path(__file__).parent.parent / "tools")
if tools_path not in sys.path:
    sys.path.append(tools_path)

import junit_html_report

from plugin_config import PluginConfig, PlatformConfig, load_plugin_config
from report_paths import build_report_location
from object_store import (
    ObjectAuth,
    StoreConfig,
    load_store_config,
    resolve_object_auth,
    upload_file,
    parse_s3,
    aws_clients,
    key_join,
    PublishedObject,
)
from report_downloads import DownloadedJobXml, collect_full_scope_xml
from xml_inputs import collect_job_xml_uploads, XmlUpload
from annotations import (
    build_annotation_body,
    get_annotation_style,
    create_buildkite_annotation,
)
from git_links import build_commit_url


@dataclass(frozen=True)
class ObjectStoreContext:
    store_cfg: StoreConfig
    auth: ObjectAuth
    bucket: str
    prefix: str


@dataclass(frozen=True)
class GenerationResult:
    html_path: Path
    summary_path: Path


def log(message: str) -> None:
    print(f"INFO  {message}", file=sys.stderr)


def warn(message: str) -> None:
    print(f"WARN  {message}", file=sys.stderr)


def aggregate_discovery_counts(
    downloaded_xml: List[DownloadedJobXml],
) -> Dict[str, int]:
    variants = {item.variant for item in downloaded_xml}
    jobs = {(item.variant, item.job_id) for item in downloaded_xml}
    return {"variants": len(variants), "jobs": len(jobs), "files": len(downloaded_xml)}


def add_summary_metadata(
    summary_path: Path, *, discovered_xml: Optional[Dict[str, int]] = None
) -> None:
    summary = json.loads(summary_path.read_text())
    if discovered_xml is not None:
        summary["discovered_xml"] = discovered_xml
    summary_path.write_text(json.dumps(summary, indent=2))


def build_zero_xml_annotation_body(title: str) -> str:
    return (
        f"## {title}\n\n"
        "No JUnit XML was found for this aggregate test report.\n\n"
        "Make sure this aggregate step depends on the test jobs that publish job reports."
    )


def run_report_generation(config: PluginConfig, output_dir: Path) -> GenerationResult:
    """
    Runs the HTML report generator and returns the paths to the generated report files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    html_path = output_dir / "index.html"
    summary_path = output_dir / "summary.json"

    junit_html_report.generate_html_report(
        title=config.title,
        platform_specs=[(p.name, p.path) for p in config.platforms],
        output=html_path,
        summary_json=summary_path,
        execution_name=config.execution_name,
        build_url=config.build_url,
        commit_url=build_commit_url(config.repo, config.commit),
        only_failures=config.only_failures,
        fail_on_test_failures=False,
    )

    return GenerationResult(
        html_path=html_path,
        summary_path=summary_path,
    )


def resolve_object_store_context() -> ObjectStoreContext:
    _s3, ssm = aws_clients()
    store_cfg = load_store_config(ssm)
    auth = resolve_object_auth(store_cfg)
    bucket, prefix = parse_s3(store_cfg.destination)
    return ObjectStoreContext(store_cfg=store_cfg, auth=auth, bucket=bucket, prefix=prefix)


def upload_report_artifacts(
    config: PluginConfig,
    generation: GenerationResult,
    xml_uploads: List[XmlUpload],
    store_context: Optional[ObjectStoreContext] = None,
) -> Dict[str, PublishedObject]:
    """
    Uploads report artifacts (HTML, summary, and job-scope XML) to the object store.
    """
    context = store_context or resolve_object_store_context()
    store_cfg = context.store_cfg
    auth = context.auth
    bucket = context.bucket
    prefix = context.prefix

    location = build_report_location(
        destination_prefix=prefix,
        project_id=config.project_id,
        git_ref=config.git_ref,
        build_id=config.build_id,
        scope=config.scope,
        job_id=config.job_id,
        variant=config.variant,
    )

    results = {}

    # HTML
    log(f"Uploading HTML report to s3://{bucket}/{location.html_key}")
    results["html"] = upload_file(
        store_cfg,
        auth,
        bucket,
        location.html_key,
        generation.html_path,
        content_type="text/html; charset=utf-8",
        content_disposition="inline",
    )

    # Summary JSON
    log(f"Uploading summary JSON to s3://{bucket}/{location.summary_key}")
    results["summary"] = upload_file(
        store_cfg,
        auth,
        bucket,
        location.summary_key,
        generation.summary_path,
        content_type="application/json",
        content_disposition="inline",
    )

    # XMLs
    if config.scope == "job":
        for xml in xml_uploads:
            key = key_join(location.xml_prefix, xml.object_relative_path)
            log(f"Uploading JUnit XML {xml.object_relative_path} to s3://{bucket}/{key}")
            results[f"xml:{xml.object_relative_path}"] = upload_file(
                store_cfg,
                auth,
                bucket,
                key,
                xml.local_path,
                content_type="application/xml",
                content_disposition="attachment",
            )

    return results


def main() -> int:
    try:
        config = load_plugin_config()

        with tempfile.TemporaryDirectory(prefix="test-report-") as tmp_dir_str:
            staging_root = Path(tmp_dir_str)
            full_scope_xml_stage_root = staging_root / "downloaded-xml"

            store_context: Optional[ObjectStoreContext] = None
            aggregate_counts: Optional[Dict[str, int]] = None
            if config.scope == "aggregate":
                store_context = resolve_object_store_context()
                log("Discovering aggregate JUnit XML from object storage")
                downloaded_xml = collect_full_scope_xml(
                    cfg=store_context.store_cfg,
                    auth=store_context.auth,
                    bucket=store_context.bucket,
                    destination_prefix=store_context.prefix,
                    project_id=config.project_id,
                    git_ref=config.git_ref,
                    build_id=config.build_id,
                    output_dir=full_scope_xml_stage_root,
                )

                if not downloaded_xml:
                    log("No JUnit XML was found for this aggregate test report.")
                    if config.annotate:
                        create_buildkite_annotation(
                            build_zero_xml_annotation_body(config.title),
                            "test-report:full",
                            "error",
                            priority=10,
                            scope="build",
                        )
                    return 0

                aggregate_counts = aggregate_discovery_counts(downloaded_xml)
                log(
                    "Discovered JUnit XML for aggregate report: "
                    f"{aggregate_counts['variants']} variants, "
                    f"{aggregate_counts['jobs']} jobs, "
                    f"{aggregate_counts['files']} XML files."
                )
                variant_names = sorted({item.variant for item in downloaded_xml})
                config = replace(
                    config,
                    platforms=[
                        PlatformConfig(
                            name=variant,
                            path=full_scope_xml_stage_root / variant,
                        )
                        for variant in variant_names
                    ],
                )
                xml_uploads = [
                    XmlUpload(
                        local_path=item.local_path,
                        object_relative_path=item.object_relative_path,
                    )
                    for item in downloaded_xml
                ]
            else:
                if config.junit_input_path is None or config.variant is None:
                    raise ValueError("scope=job requires variant and junit_input_path")
                xml_uploads = collect_job_xml_uploads(config.junit_input_path, config.variant)

            # Create temp dir for HTML report generation output
            tmp_base = staging_root / "report"

            # Generate report
            log(
                f"Generating {config.scope} report"
                + (f" for variant {config.variant}" if config.variant else "")
            )
            generation = run_report_generation(config, tmp_base)
            if config.scope == "aggregate":
                add_summary_metadata(generation.summary_path, discovered_xml=aggregate_counts)

            # Upload JUNIT reports, HTML report, summary
            uploads = upload_report_artifacts(
                config, generation, xml_uploads, store_context=store_context
            )

            # Create annotation if enabled and HTML URL is available
            if config.annotate:
                html_url = uploads["html"].url
                if not html_url:
                    warn(
                        "HTML public URL unavailable (ARTIFACTS_DOMAIN not set); skipping annotation"
                    )
                else:
                    summary = json.loads(generation.summary_path.read_text())
                    body = build_annotation_body(config.title, summary, html_url)
                    style = get_annotation_style(summary)

                    if config.scope == "job":
                        context = f"test-report:{config.variant}:{config.job_id}"
                        create_buildkite_annotation(body, context, style, priority=10, scope="job")
                    else:
                        context = "test-report:full"
                        create_buildkite_annotation(
                            body, context, style, priority=10, scope="build"
                        )

            # Exit with failure code if any test failed or errored and fail_on_test_failures is true
            summary = json.loads(generation.summary_path.read_text())
            status_counts = summary.get("status_counts", {})
            failed_or_errored = int(status_counts.get("FAILED", 0)) + int(
                status_counts.get("ERRORED", 0)
            )
            if config.fail_on_test_failures and failed_or_errored:
                log(
                    f"Report has {failed_or_errored} failed/errored test execution(s) and fail_on_test_failures=true. Exiting 64."
                )
                return 64

            return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
