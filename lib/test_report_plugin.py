from __future__ import annotations

import json
import mimetypes
import os
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

# Add tools to path so we can import junit_html_report tool
tools_path = str(Path(__file__).parent.parent / "tools")
if tools_path not in sys.path:
    sys.path.append(tools_path)

import junit_html_report
from annotations import (
    build_annotation_body,
    create_buildkite_annotation,
    get_annotation_style,
    get_job_annotation_style,
)
from artifact_inputs import ArtifactFile, collect_artifact_files, slugify_artifact_name
from execution_inputs import collect_execution_inputs
from git_links import build_commit_url
from junit_report_model import ArtifactLink
from object_store import (
    ObjectAuth,
    PublishedObject,
    StoreConfig,
    UploadRequest,
    aws_clients,
    internal_url,
    key_join,
    load_store_config,
    parse_s3,
    resolve_object_auth,
    upload_file,
    upload_files,
)
from plugin_config import PlatformConfig, PluginConfig, load_plugin_config
from report_downloads import (
    DownloadedJobXml,
    collect_full_scope_job_summaries,
    collect_full_scope_job_summaries_for_xml,
    collect_full_scope_xml,
)
from report_logging import configure_logging, logger, trace, trace_timings, traced
from report_paths import build_report_location
from xml_inputs import XmlUpload, collect_job_xml_uploads


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


@dataclass(frozen=True)
class XmlSourceLink:
    key: str
    url: str | None


ArtifactMetadata = List[Dict[str, Any]]


def log(message: str) -> None:
    logger.info(message)


def warn(message: str) -> None:
    logger.warning(message)


def aggregate_discovery_counts(
    downloaded_xml: list[DownloadedJobXml],
) -> dict[str, int]:
    variants = {item.variant for item in downloaded_xml}
    jobs = {(item.variant, item.job_id) for item in downloaded_xml}
    return {"variants": len(variants), "jobs": len(jobs), "files": len(downloaded_xml)}


@traced("summary.metadata")
def add_summary_metadata(
    summary_path: Path,
    *,
    discovered_xml: dict[str, int] | None = None,
    job_artifacts: ArtifactMetadata | None = None,
) -> None:
    summary = json.loads(summary_path.read_text())
    if discovered_xml is not None:
        summary["discovered_xml"] = discovered_xml
    if job_artifacts is not None:
        summary["job_artifacts"] = job_artifacts
    summary_path.write_text(json.dumps(summary, indent=2))


def add_command_failure_warning(summary: dict[str, Any], command_exit_status: str | None) -> bool:
    if command_exit_status in (None, "", "0"):
        return False

    try:
        exit_status = int(command_exit_status)
    except ValueError:
        return False

    if exit_status == 0:
        return False

    counts = summary.get("logical_status_counts") or summary.get("status_counts", {})
    passed = int(counts.get("SUCCESSFUL", 0))
    failed = int(counts.get("FAILED", 0))
    errored = int(counts.get("ERRORED", 0))
    skipped = int(counts.get("SKIPPED", 0))
    if passed == 0 or failed or errored or skipped:
        return False

    summary.setdefault("warnings", []).append(
        f"Step command exited with status {exit_status} although all reported tests passed."
    )
    return True


@traced("artifacts.links", category="report_metadata")
def artifact_links_from_metadata(metadata: ArtifactMetadata) -> list[ArtifactLink]:
    links: list[ArtifactLink] = []
    for artifact in metadata:
        for file_info in artifact.get("files", []):
            links.append(
                ArtifactLink(
                    name=str(artifact.get("name", "Artifact")),
                    relative_path=str(file_info.get("relative_path", "")),
                    key=str(file_info.get("key", "")),
                    url=file_info.get("url"),
                    size_bytes=int(file_info.get("size_bytes", 0)),
                    execution_id=file_info.get("execution_id"),
                )
            )
    return links


@traced("job.xml.links", category="report_metadata")
def build_job_xml_source_links(
    config: PluginConfig,
    xml_uploads: list[XmlUpload],
    store_context: ObjectStoreContext,
) -> dict[Path, XmlSourceLink]:
    location = build_report_location(
        destination_prefix=store_context.prefix,
        project_id=config.project_id,
        git_ref=config.git_ref,
        build_id=config.build_id,
        scope=config.scope,
        job_id=config.job_id,
        variant=config.variant,
    )
    links: dict[Path, XmlSourceLink] = {}
    for xml in xml_uploads:
        key = key_join(location.xml_prefix, "junit.zip")
        links[xml.local_path.resolve()] = XmlSourceLink(
            key=key, url=archive_member_url(store_context.store_cfg, key, xml.object_relative_path)
        )
    return links


@traced("aggregate.xml.links", category="report_metadata")
def build_aggregate_xml_source_links(
    downloaded_xml: list[DownloadedJobXml], store_context: ObjectStoreContext
) -> dict[Path, XmlSourceLink]:
    return {
        item.local_path.resolve(): XmlSourceLink(
            key=item.object.key,
            url=(
                archive_member_url(
                    store_context.store_cfg, item.object.key, item.object.archive_member
                )
                if item.object.archive_member is not None
                else internal_url(store_context.store_cfg, item.object.key)
            ),
        )
        for item in downloaded_xml
    }


def build_zero_xml_annotation_body(title: str) -> str:
    return (
        f"## {title}\n\n"
        "No JUnit XML was found for this aggregate test report.\n\n"
        "Make sure this aggregate step depends on the test jobs that publish job reports."
    )


@traced("report.generate", category="report_generation")
def run_report_generation(
    config: PluginConfig,
    output_dir: Path,
    *,
    source_artifacts_by_job_id: dict[str, list[ArtifactLink]] | None = None,
    artifacts: list[ArtifactLink] | None = None,
    artifact_metadata: ArtifactMetadata | None = None,
    xml_source_links: dict[Path, XmlSourceLink] | None = None,
    junit_archive_errors: list[dict[str, str]] | None = None,
) -> GenerationResult:
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
        source_job_id=config.job_id,
        source_artifacts_by_job_id=source_artifacts_by_job_id,
        artifacts=artifacts,
        artifact_metadata=artifact_metadata,
        xml_source_links={path: link.url for path, link in (xml_source_links or {}).items()},
        junit_archive_errors=junit_archive_errors,
        only_failures=config.only_failures,
        fail_on_test_failures=False,
        log_level=config.log_level,
        parse_workers=config.aggregate_parse_workers if config.scope == "aggregate" else 1,
    )

    return GenerationResult(
        html_path=html_path,
        summary_path=summary_path,
    )


@traced("store.resolve")
def resolve_object_store_context() -> ObjectStoreContext:
    _s3, ssm = aws_clients()
    store_cfg = load_store_config(ssm)
    auth = resolve_object_auth(store_cfg)
    bucket, prefix = parse_s3(store_cfg.destination)
    return ObjectStoreContext(store_cfg=store_cfg, auth=auth, bucket=bucket, prefix=prefix)


def guessed_content_type(path: Path) -> str:
    if path.name.endswith(".gz"):
        return "application/gzip"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def archive_member_url(cfg: StoreConfig, key: str, member: str) -> str | None:
    url = internal_url(cfg, key)
    return f"{url}#zip-member={quote(member, safe='')}" if url else None


def create_zip(files: list[tuple[Path, str]], output: Path) -> None:
    with trace("archive.create", archive=output.name, files=len(files)):
        with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=1) as archive:
            for path, name in files:
                # Already-compressed logs do not benefit from another compression pass.
                compression = ZIP_STORED if path.suffix in {".gz", ".zip", ".zst"} else ZIP_DEFLATED
                archive.write(path, name, compress_type=compression)
        log(f"Created ZIP archive={output.name} files={len(files)} bytes={output.stat().st_size}")


@traced("artifacts.upload", category="uploads")
def upload_extra_artifacts(
    config: PluginConfig,
    artifact_files: list[ArtifactFile],
    store_context: ObjectStoreContext,
) -> ArtifactMetadata:
    location = build_report_location(
        destination_prefix=store_context.prefix,
        project_id=config.project_id,
        git_ref=config.git_ref,
        build_id=config.build_id,
        scope=config.scope,
        job_id=config.job_id,
        variant=config.variant,
    )

    requests = [
        UploadRequest(
            key=key_join(
                location.artifact_prefix,
                slugify_artifact_name(item.config.name),
                item.relative_path,
            ),
            local_path=item.local_path,
            content_type=guessed_content_type(item.local_path),
            content_disposition="attachment",
        )
        for item in artifact_files
    ]
    if artifact_files:
        with tempfile.TemporaryDirectory(prefix="test-report-logs-") as tmp_dir:
            archive_path = Path(tmp_dir) / "logs.zip"
            create_zip(
                [
                    (
                        item.local_path,
                        key_join(slugify_artifact_name(item.config.name), item.relative_path),
                    )
                    for item in artifact_files
                ],
                archive_path,
            )
            upload_files(
                store_context.store_cfg,
                store_context.auth,
                store_context.bucket,
                [
                    UploadRequest(
                        key_join(location.artifact_prefix, "logs.zip"),
                        archive_path,
                        "application/zip",
                        "attachment",
                    )
                ],
                parallel=config.upload_parallel,
            )
    grouped: dict[str, dict[str, Any]] = {}
    for artifact_file, request in zip(artifact_files, requests):
        archive_key = key_join(location.artifact_prefix, "logs.zip")
        member = key_join(
            slugify_artifact_name(artifact_file.config.name), artifact_file.relative_path
        )
        published = PublishedObject(
            bucket=store_context.bucket,
            key=archive_key,
            url=archive_member_url(store_context.store_cfg, archive_key, member),
            size_bytes=request.local_path.stat().st_size,
        )
        artifact = artifact_file.config
        entry = grouped.setdefault(
            artifact.name,
            {
                "name": artifact.name,
                "input_path": str(artifact.input_path),
                "files": [],
                "warnings": [],
            },
        )
        file_info: dict[str, Any] = {
            "relative_path": artifact_file.relative_path,
            "key": published.key,
            "archive_member": member,
            "size_bytes": published.size_bytes,
        }
        if published.url:
            file_info["url"] = published.url
        entry["files"].append(file_info)
    return list(grouped.values())


@traced("report.upload", category="uploads")
def upload_report_artifacts(
    config: PluginConfig,
    generation: GenerationResult,
    xml_uploads: list[XmlUpload],
    store_context: ObjectStoreContext | None = None,
) -> dict[str, PublishedObject]:
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

    requests = [
        UploadRequest(
            key=location.html_key,
            local_path=generation.html_path,
            content_type="text/html; charset=utf-8",
            content_disposition="inline",
        )
    ]
    job_xml = xml_uploads if config.scope == "job" else []
    if job_xml:
        archive_path = generation.html_path.parent / "junit.zip"
        create_zip([(xml.local_path, xml.object_relative_path) for xml in job_xml], archive_path)
        requests.append(
            UploadRequest(
                key=key_join(location.xml_prefix, "junit.zip"),
                local_path=archive_path,
                content_type="application/zip",
                content_disposition="attachment",
            )
        )
    published = upload_files(store_cfg, auth, bucket, requests, parallel=config.upload_parallel)
    # Publish the discovery manifest only after all HTML/XML uploads succeed.
    log(f"Uploading summary JSON to s3://{bucket}/{location.summary_key}")
    summary = upload_file(
        store_cfg,
        auth,
        bucket,
        location.summary_key,
        generation.summary_path,
        content_type="application/json",
        content_disposition="inline",
    )
    results = {"html": published[0], "summary": summary}
    if job_xml:
        results["xml_archive"] = published[1]

    return results


def main() -> int:
    trace_timings.clear()
    trace_timings.update(
        dict.fromkeys(
            (
                "total",
                "storage_setup",
                "input_collection",
                "downloads",
                "report_generation",
                "report_metadata",
                "uploads",
                "annotations",
            ),
            0.0,
        )
    )

    try:
        config = load_plugin_config()
        configure_logging(config.log_level)

        with trace(
            "plugin.total", category="total", scope=config.scope
        ), tempfile.TemporaryDirectory(prefix="test-report-") as tmp_dir_str:
            staging_root = Path(tmp_dir_str)
            full_scope_xml_stage_root = staging_root / "downloaded-xml"

            store_context: ObjectStoreContext | None = None
            aggregate_counts: dict[str, int] | None = None
            artifact_metadata: ArtifactMetadata = []
            job_artifacts_metadata: ArtifactMetadata = []
            source_artifacts_by_job_id: dict[str, list[ArtifactLink]] = {}
            report_artifacts: list[ArtifactLink] = []
            xml_source_links: dict[Path, XmlSourceLink] = {}
            junit_archive_errors: list[dict[str, str]] = []
            if config.scope == "aggregate":
                with trace("plugin.store_setup", category="storage_setup"):
                    store_context = resolve_object_store_context()
                log("Discovering aggregate JUnit XML object keys from object storage")
                downloaded_xml = collect_full_scope_xml(
                    cfg=store_context.store_cfg,
                    auth=store_context.auth,
                    bucket=store_context.bucket,
                    destination_prefix=store_context.prefix,
                    project_id=config.project_id,
                    git_ref=config.git_ref,
                    build_id=config.build_id,
                    output_dir=full_scope_xml_stage_root,
                    download_parallel=config.aggregate_download_parallel,
                    download_concurrency=config.aggregate_download_concurrency,
                    log_fn=log,
                    archive_errors=junit_archive_errors,
                )

                if not downloaded_xml and not junit_archive_errors:
                    logger.error("No JUnit XML was found for this aggregate test report.")
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
                xml_source_links = build_aggregate_xml_source_links(downloaded_xml, store_context)
                log(
                    "Discovered JUnit XML for aggregate report: "
                    f"{aggregate_counts['variants']} variants, "
                    f"{aggregate_counts['jobs']} jobs, "
                    f"{aggregate_counts['files']} XML files."
                )
                variant_names = sorted(
                    {item.variant for item in downloaded_xml}
                    | {item["platform"] for item in junit_archive_errors}
                )
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
                log("Discovering aggregate job summary manifests")
                job_summaries = collect_full_scope_job_summaries_for_xml(
                    cfg=store_context.store_cfg,
                    auth=store_context.auth,
                    bucket=store_context.bucket,
                    downloaded_xml=downloaded_xml,
                    output_dir=staging_root / "downloaded-summaries",
                    download_parallel=config.aggregate_download_parallel,
                )
                if not job_summaries:
                    job_summaries = collect_full_scope_job_summaries(
                        cfg=store_context.store_cfg,
                        auth=store_context.auth,
                        bucket=store_context.bucket,
                        destination_prefix=store_context.prefix,
                        project_id=config.project_id,
                        git_ref=config.git_ref,
                        build_id=config.build_id,
                        output_dir=staging_root / "downloaded-summaries",
                    )
                for summary in job_summaries.values():
                    artifacts = summary.get("artifacts", [])
                    job_id = str(summary.get("job_id", ""))
                    job_artifacts_metadata.append(
                        {
                            "variant": summary.get("variant"),
                            "job_id": job_id,
                            "artifacts": artifacts,
                        }
                    )
                    source_artifacts_by_job_id[job_id] = artifact_links_from_metadata(artifacts)
                artifact_file_count = sum(
                    len(artifact.get("files", []))
                    for summary in job_summaries.values()
                    for artifact in summary.get("artifacts", [])
                )
                log(
                    "Discovered aggregate job summaries: "
                    f"{len(job_summaries)} summaries, {artifact_file_count} artifact files."
                )
                report_artifacts = [
                    link for links in source_artifacts_by_job_id.values() for link in links
                ]
            else:
                if config.variant is None:
                    raise ValueError("scope=job requires variant")
                if config.junit_input_path is None and config.manifest_input_path is None:
                    raise ValueError("scope=job requires junit_input_path or manifest_input_path")
                with trace("job.inputs", category="input_collection"):
                    xml_uploads = []
                    if config.junit_input_path is not None:
                        try:
                            xml_uploads = collect_job_xml_uploads(
                                config.junit_input_path, config.variant
                            )
                        except FileNotFoundError:
                            if config.manifest_input_path is None:
                                raise
                    execution_inputs = None
                    if config.manifest_input_path is not None:
                        execution_inputs = collect_execution_inputs(
                            config.manifest_input_path, xml_uploads, staging_root / "executions"
                        )
                        xml_uploads = execution_inputs.xml_uploads
                        if not xml_uploads:
                            raise FileNotFoundError("No JUnit reports or execution manifests found")
                        config = replace(
                            config,
                            platforms=[
                                PlatformConfig(config.variant, xml.local_path)
                                for xml in xml_uploads
                            ],
                        )
                with trace("plugin.store_setup", category="storage_setup"):
                    store_context = resolve_object_store_context()
                xml_source_links = build_job_xml_source_links(config, xml_uploads, store_context)
                with trace("job.artifact_inputs", category="input_collection"):
                    artifact_files = collect_artifact_files(config.artifacts)
                if execution_inputs is not None:
                    if any(
                        slugify_artifact_name(artifact.name)
                        == slugify_artifact_name("Test execution artifacts")
                        for artifact in config.artifacts
                    ):
                        raise ValueError(
                            "Test execution artifacts is reserved for launcher manifests"
                        )
                    artifact_files.extend(execution_inputs.artifact_files)
                if artifact_files:
                    artifact_metadata = upload_extra_artifacts(
                        config, artifact_files, store_context
                    )
                if execution_inputs is not None:
                    for artifact in artifact_metadata:
                        if artifact["name"] == "Test execution artifacts":
                            for file_info in artifact["files"]:
                                file_info["execution_id"] = execution_inputs.execution_ids[
                                    file_info["relative_path"]
                                ]
                uploaded_artifact_names = {item["name"] for item in artifact_metadata}
                for artifact in config.artifacts:
                    if artifact.name not in uploaded_artifact_names:
                        artifact_metadata.append(
                            {
                                "name": artifact.name,
                                "input_path": str(artifact.input_path),
                                "files": [],
                                "warnings": ["no files found for configured artifact input_path"],
                            }
                        )
                if config.job_id:
                    source_artifacts_by_job_id[config.job_id] = artifact_links_from_metadata(
                        artifact_metadata
                    )
                report_artifacts = artifact_links_from_metadata(artifact_metadata)

            # Create temp dir for HTML report generation output
            tmp_base = staging_root / "report"

            # Generate report
            log(
                f"Generating {config.scope} report"
                + (f" for variant {config.variant}" if config.variant else "")
            )
            generation = run_report_generation(
                config,
                tmp_base,
                source_artifacts_by_job_id=source_artifacts_by_job_id,
                artifacts=report_artifacts if config.scope == "job" else [],
                artifact_metadata=artifact_metadata if config.scope == "job" else None,
                xml_source_links=xml_source_links,
                junit_archive_errors=junit_archive_errors,
            )
            with trace("summary.prepare", category="report_metadata"):
                if config.scope == "aggregate":
                    add_summary_metadata(
                        generation.summary_path,
                        discovered_xml=aggregate_counts,
                        job_artifacts=job_artifacts_metadata,
                    )

                summary = json.loads(generation.summary_path.read_text())
                if config.scope == "job" and add_command_failure_warning(
                    summary, os.environ.get("BUILDKITE_COMMAND_EXIT_STATUS")
                ):
                    generation.summary_path.write_text(json.dumps(summary, indent=2))

            # Upload JUNIT reports, HTML report, summary
            uploads = upload_report_artifacts(
                config, generation, xml_uploads, store_context=store_context
            )
            html_upload = uploads.get("html")
            if html_upload is not None:
                if html_upload.url:
                    log(f"HTML report: {html_upload.url}")
                else:
                    log(f"HTML report uploaded to s3://{html_upload.bucket}/{html_upload.key}")

            # Preserve malformed-input diagnostics even when no public HTML URL is available.
            if config.annotate:
                html_url = html_upload.url if html_upload is not None else None
                if config.scope == "job":
                    style = get_job_annotation_style(summary)
                else:
                    style = get_annotation_style(summary)
                if (
                    not html_url
                    and style != "warning"
                    and not summary.get("malformed_junit_xml")
                    and not summary.get("junit_archive_errors")
                ):
                    warn(
                        "HTML public URL unavailable (ARTIFACTS_DOMAIN not set); skipping annotation"
                    )
                else:
                    body = build_annotation_body(
                        config.title,
                        summary,
                        html_url,
                        scope=config.scope,
                        annotation_report_limit=config.annotation_report_limit,
                    )
                    if config.scope == "job":
                        context = f"test-report:{config.variant}:{config.job_id}"
                        create_buildkite_annotation(body, context, style, priority=10, scope="job")
                    else:
                        context = "test-report:full"
                        create_buildkite_annotation(
                            body, context, style, priority=10, scope="build"
                        )

            # Exit with failure code if any test failed or errored and fail_on_test_failures is true
            status_counts = summary.get("status_counts", {})
            failed_or_errored = int(status_counts.get("FAILED", 0)) + int(
                status_counts.get("ERRORED", 0)
            )
            malformed_junit_xml = summary.get("malformed_junit_xml", [])
            if summary.get("junit_archive_errors"):
                logger.error("Report contains rejected JUnit archives. Exiting 1.")
                return 1
            if config.fail_on_test_failures and (failed_or_errored or malformed_junit_xml):
                logger.error(
                    f"Report has {failed_or_errored} failed/errored test execution(s) and "
                    f"{len(malformed_junit_xml)} malformed JUnit XML file(s); "
                    "fail_on_test_failures=true. Exiting 64."
                )
                return 64

            return 0
    except Exception as exc:  # noqa: BLE001 - plugin CLI boundary
        logger.fatal("Test report plugin failed: %s", exc)
        return 1
    finally:
        total = trace_timings["total"]
        timings = {
            category: elapsed for category, elapsed in trace_timings.items() if category != "total"
        }
        timings["overhead"] = max(0.0, total - sum(timings.values()))
        parts = [f"total={total:.1f}s"]
        parts.extend(
            f"{stage}={elapsed:.1f}s"
            for stage, elapsed in timings.items()
            if f"{elapsed:.1f}" != "0.0"
        )
        # Keep the summary visible at default verbosity without labeling it as an error.
        logger.error(
            "Timing summary: %s",
            " ".join(parts),
            extra={"omit_level": True},
        )


if __name__ == "__main__":
    sys.exit(main())
