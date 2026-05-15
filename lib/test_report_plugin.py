from __future__ import annotations
from typing import Dict, List, Optional
import sys
import json
import os
from pathlib import Path
from dataclasses import dataclass, replace

# Add tools to path so we can import junit_html_report tool
tools_path = str(Path(__file__).parent.parent / "tools")
if tools_path not in sys.path:
    sys.path.append(tools_path)

import junit_html_report

from plugin_config import PluginConfig, PlatformConfig, load_plugin_config
from report_paths import build_report_location, ReportLocation
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
from report_downloads import collect_full_scope_xml, build_job_xml_prefix
from xml_inputs import collect_xml_uploads, XmlUpload
from annotations import (
    build_annotation_body,
    get_annotation_style,
    create_buildkite_annotation,
)
from git_links import build_commit_url

FULL_SCOPE_XML_STAGE_ROOT = Path(".buildkite-test-report") / "downloaded-xml"


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


def full_scope_missing_variants(
    platforms: List[PlatformConfig], xml_uploads: List[XmlUpload]
) -> List[str]:
    """Return configured full-scope variants that have no collected XML files."""
    variants_with_xml = {
        upload.object_relative_path.split("/", 1)[0]
        for upload in xml_uploads
        if "/" in upload.object_relative_path
    }
    return [
        platform.name
        for platform in platforms
        if platform.name not in variants_with_xml
    ]


def add_summary_warnings(summary_path: Path, warnings: List[str]) -> None:
    if not warnings:
        return

    summary = json.loads(summary_path.read_text())
    existing = list(summary.get("warnings", []))
    existing.extend(warnings)
    summary["warnings"] = existing
    summary_path.write_text(json.dumps(summary, indent=2))


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


def resolve_object_store_context(permission: str) -> ObjectStoreContext:
    _s3, ssm = aws_clients()
    store_cfg = load_store_config(ssm)
    auth = resolve_object_auth(ssm, store_cfg, permission)
    bucket, prefix = parse_s3(store_cfg.destination)
    return ObjectStoreContext(
        store_cfg=store_cfg, auth=auth, bucket=bucket, prefix=prefix
    )


def upload_report_artifacts(
    config: PluginConfig,
    generation: GenerationResult,
    xml_uploads: List[XmlUpload],
    store_context: Optional[ObjectStoreContext] = None,
) -> Dict[str, PublishedObject]:
    """
    Uploads report artifacts (HTML, summary, and job-scope XML) to the object store.
    """
    context = store_context or resolve_object_store_context("upload")
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
    print(
        f"INFO  Uploading HTML report to s3://{bucket}/{location.html_key}",
        file=sys.stderr,
    )
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
    print(
        f"INFO  Uploading summary JSON to s3://{bucket}/{location.summary_key}",
        file=sys.stderr,
    )
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
            print(
                f"INFO  Uploading JUnit XML {xml.object_relative_path} to s3://{bucket}/{key}",
                file=sys.stderr,
            )
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


def main():
    try:
        config = load_plugin_config()

        store_context: Optional[ObjectStoreContext] = None
        if config.scope == "full":
            store_context = resolve_object_store_context("object-read-write")
            variants = [platform.name for platform in config.platforms]
            print(
                f"INFO  Downloading full-scope JUnit XML for variants: {', '.join(variants)}",
                file=sys.stderr,
            )
            collect_full_scope_xml(
                cfg=store_context.store_cfg,
                auth=store_context.auth,
                bucket=store_context.bucket,
                destination_prefix=store_context.prefix,
                project_id=config.project_id,
                git_ref=config.git_ref,
                build_id=config.build_id,
                variants=variants,
                output_dir=FULL_SCOPE_XML_STAGE_ROOT,
            )
            config = replace(
                config,
                platforms=[
                    PlatformConfig(
                        name=platform.name,
                        path=FULL_SCOPE_XML_STAGE_ROOT / platform.name,
                    )
                    for platform in config.platforms
                ],
            )

        # Collect XMLs first to ensure they exist. For full runs this reads
        # the object-store staging directory populated above.
        xml_uploads = collect_xml_uploads(config.platforms, config.scope)
        summary_warnings: List[str] = []
        if config.scope == "full":
            missing_variants = full_scope_missing_variants(
                config.platforms, xml_uploads
            )
            if missing_variants:
                variant_list = ", ".join(missing_variants)
                warning = (
                    f"Missing full-scope report variants: {variant_list}. "
                    "This usually means a job failed before publishing test XML."
                )
                print(f"WARN  {warning}", file=sys.stderr)
                summary_warnings.append(warning)

        # Create temp dir for HTML report generation output. For job scope or full scope with variant, we can use a stable path to allow in-place updates; otherwise we use a unique temp dir.
        variant_or_full = (
            config.variant
            if (config.scope == "job" or (config.scope == "full" and config.variant))
            else "full"
        )
        tmp_base = Path(".buildkite-test-report") / config.scope / variant_or_full

        # Generate report
        print(f"INFO  Generating {config.scope} report", file=sys.stderr)
        generation = run_report_generation(config, tmp_base)
        add_summary_warnings(generation.summary_path, summary_warnings)

        # Upload JUNIT reports, HTML report, summary
        uploads = upload_report_artifacts(
            config, generation, xml_uploads, store_context=store_context
        )

        # Create annotation if enabled and HTML URL is available
        if config.annotate:
            html_url = uploads["html"].url
            if not html_url:
                print(
                    "WARNING: HTML public URL unavailable (ARTIFACTS_DOMAIN not set); skipping annotation",
                    file=sys.stderr,
                )
            else:
                summary = json.loads(generation.summary_path.read_text())
                body = build_annotation_body(config.title, summary, html_url)
                style = get_annotation_style(summary)

                if config.scope == "job":
                    context = f"test-report:{config.variant}:{config.job_id}"
                    create_buildkite_annotation(
                        body, context, style, priority=10, scope="job"
                    )
                else:
                    context = (
                        f"test-report:{config.variant}:full"
                        if config.variant
                        else "test-report:full"
                    )
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
            print(
                f"INFO  Report has {failed_or_errored} failed/errored test execution(s) and fail_on_test_failures=true. Exiting 64.",
                file=sys.stderr,
            )
            return 64

        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
