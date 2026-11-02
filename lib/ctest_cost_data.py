"""Restore CTest scheduling costs from immutable job-report descriptors."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError
from object_store import create_s3_client
from plugin_config import PluginConfig, load_plugin_config
from report_logging import configure_logging, logger
from report_paths import (
    build_ctest_cost_data_descriptor_key,
    build_ctest_cost_data_discovery_prefix,
    build_report_location,
)
from test_report_plugin import ObjectStoreContext, resolve_object_store_context

MAX_DISCOVERY_OBJECTS = 1000
MAX_DESCRIPTORS = 50
MAX_DESCRIPTOR_BYTES = 64 * 1024
MAX_COST_BYTES = 4 * 1024 * 1024


def read_object(client, bucket: str, key: str, limit: int) -> bytes:
    response = client.get_object(Bucket=bucket, Key=key)
    body = response["Body"]
    try:
        if response.get("ContentLength", 0) > limit:
            raise ValueError("object exceeds restoration size limit")
        data = body.read(limit + 1)
        if len(data) > limit:
            raise ValueError("object exceeds restoration size limit")
        return data
    finally:
        body.close()


def list_descriptor_candidates(client, bucket: str, prefix: str, current_build: int):
    candidates = []
    count = 0
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(
        Bucket=bucket, Prefix=prefix, PaginationConfig={"PageSize": 1000}
    ):
        objects = page.get("Contents", [])
        count += len(objects)
        if count > MAX_DISCOVERY_OBJECTS:
            raise ValueError("CTest cost discovery object limit exceeded")
        for item in objects:
            key = item["Key"]
            if not key.startswith(prefix):
                continue
            parts = key[len(prefix) :].split("/")
            if len(parts) != 2 or not parts[0].isdigit() or not parts[1].endswith(".json"):
                continue
            number = int(parts[0])
            if 0 < number < current_build and item.get("Size", 0) <= MAX_DESCRIPTOR_BYTES:
                candidates.append((number, key))
        if count == MAX_DISCOVERY_OBJECTS and page.get("IsTruncated"):
            raise ValueError("CTest cost discovery object limit exceeded")
    candidates.sort(reverse=True)
    if len(candidates) > MAX_DESCRIPTORS:
        logger.warning("CTest cost discovery limited to the newest %s descriptors", MAX_DESCRIPTORS)
    return candidates[:MAX_DESCRIPTORS]


def match_descriptor(
    metadata: dict,
    descriptor_key: str,
    config: PluginConfig,
    context: ObjectStoreContext,
    git_ref: str,
    step_key: str,
    current_build: int,
) -> bool:
    if not isinstance(metadata, dict):
        return False
    if type(metadata.get("version")) is not int:
        return False
    expected = {
        "version": 1,
        "project_id": config.project_id,
        "git_ref": git_ref,
        "variant": config.variant,
        "step_key": step_key,
        "selection": sorted(set(config.ctest_cost_data_selection)),
    }
    if any(metadata.get(key) != value for key, value in expected.items()):
        return False
    number = metadata.get("build_number")
    if type(number) is not int or not 0 < number < current_build:
        return False
    if metadata.get("build_id") == config.build_id:
        return False
    for field in ("build_id", "job_id"):
        if not isinstance(metadata.get(field), str) or not metadata[field]:
            return False
    status = metadata.get("command_exit_status")
    if type(status) is not int or status != 0:
        return False
    counts = metadata.get("status_counts")
    if not isinstance(counts, dict) or not counts:
        return False
    if any(type(value) is not int or value < 0 for value in counts.values()):
        return False
    if set(counts) - {"SUCCESSFUL", "FAILED", "ERRORED", "SKIPPED"}:
        return False
    if counts.get("SUCCESSFUL", 0) < 1 or counts.get("FAILED", 0) or counts.get("ERRORED", 0):
        return False
    retry = metadata.get("retry_count")
    if retry is not None and (type(retry) is not int or retry < 0):
        return False
    size = metadata.get("size_bytes")
    if type(size) is not int or not 0 < size <= MAX_COST_BYTES:
        return False
    location = build_report_location(
        destination_prefix=context.prefix,
        project_id=config.project_id,
        git_ref=git_ref,
        build_id=metadata["build_id"],
        scope="job",
        job_id=metadata["job_id"],
        variant=config.variant,
    )
    expected_descriptor = build_ctest_cost_data_descriptor_key(
        destination_prefix=context.prefix,
        project_id=config.project_id,
        git_ref=git_ref,
        variant=config.variant,
        step_key=step_key,
        build_number=number,
        job_id=metadata["job_id"],
    )
    return (
        metadata.get("key") == location.base_prefix + "/CTestCostData.txt"
        and metadata.get("summary_key") == location.summary_key
        and descriptor_key == expected_descriptor
    )


def sanitize_cost_data(data: bytes) -> bytes:
    lines = data.decode("utf-8").splitlines()
    separator = lines.index("---")
    costs = lines[:separator]
    if not costs:
        raise ValueError("CTest cost file contains no test costs")
    for line in costs:
        name, runs_text, cost_text = line.rsplit(None, 2)
        runs = int(runs_text)
        cost = float(cost_text)
        if not name or "\x00" in name or runs < 0 or not math.isfinite(cost) or cost < 0:
            raise ValueError("invalid CTest cost entry")
    return ("\n".join(costs) + "\n---\n").encode("utf-8")


def restore_cost_data(config: PluginConfig, output: Path) -> bool:
    restore = config.ctest_cost_data_restore
    step_key = os.environ.get("BUILDKITE_STEP_KEY")
    current_build = int(os.environ.get("BUILDKITE_BUILD_NUMBER", "0"))
    if config.scope != "job" or restore is None:
        return False
    if not step_key or current_build < 1 or not config.ctest_cost_data_selection:
        logger.warning(
            "CTest cost restoration requires a build number, step key, and explicit selection"
        )
        return False
    context = resolve_object_store_context()
    client = create_s3_client(context.store_cfg, context.auth)
    refs = [config.git_ref]
    if restore.fallback_branch:
        fallback = "refs/heads/" + restore.fallback_branch
        if fallback not in refs:
            refs.append(fallback)
    try:
        for git_ref in refs:
            prefix = build_ctest_cost_data_discovery_prefix(
                destination_prefix=context.prefix,
                project_id=config.project_id,
                git_ref=git_ref,
                variant=config.variant,
                step_key=step_key,
            )
            try:
                candidates = list_descriptor_candidates(
                    client, context.bucket, prefix, current_build
                )
            except (BotoCoreError, ClientError, OSError, ValueError) as exc:
                logger.warning("CTest cost discovery unavailable for %s: %s", git_ref, exc)
                continue
            matches = []
            for _, key in candidates:
                try:
                    metadata = json.loads(
                        read_object(client, context.bucket, key, MAX_DESCRIPTOR_BYTES)
                    )
                    if match_descriptor(
                        metadata, key, config, context, git_ref, step_key, current_build
                    ):
                        matches.append(metadata)
                except (BotoCoreError, ClientError, OSError, ValueError) as exc:
                    logger.warning("Skipping unreadable CTest cost descriptor %s: %s", key, exc)
            matches.sort(
                key=lambda item: (
                    item["build_number"],
                    item.get("retry_count") if item.get("retry_count") is not None else -1,
                    item["job_id"],
                ),
                reverse=True,
            )
            for metadata in matches:
                try:
                    raw = read_object(client, context.bucket, metadata["key"], MAX_COST_BYTES)
                    if len(raw) != metadata["size_bytes"]:
                        raise ValueError("CTest cost file size differs from descriptor")
                    sanitized = sanitize_cost_data(raw)
                except (BotoCoreError, ClientError, OSError, ValueError) as exc:
                    logger.warning(
                        "Skipping unusable CTest cost snapshot %s: %s", metadata["key"], exc
                    )
                    continue
                output.write_bytes(sanitized)
                logger.info(
                    "Restored CTest costs from %s build %s job %s",
                    git_ref,
                    metadata["build_number"],
                    metadata["job_id"],
                )
                return True
        logger.warning("No matching CTest cost snapshot found; continuing with cold scheduling")
        return False
    finally:
        client.close()


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        config = load_plugin_config()
        configure_logging(config.log_level)
        restore = config.ctest_cost_data_restore
        if config.scope != "job" or restore is None:
            return 0
        if args:
            if len(args) != 2 or args[0] != "--worker":
                raise ValueError("invalid restoration worker arguments")
            restore_cost_data(config, Path(args[1]))
            return 0
        staging = restore.staging_path
        if (
            config.ctest_cost_data_path is not None
            and staging.resolve() == config.ctest_cost_data_path.resolve()
        ):
            raise ValueError(
                "restoration staging_path must differ from the archived cost-data path"
            )
        # Clear a previous job's staged snapshot before discovery, including cold misses.
        if staging.exists():
            staging.unlink()
        staging.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="ctest-cost-", dir=str(staging.parent)
        ) as directory:
            output = Path(directory) / "restored.txt"
            subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--worker", str(output.resolve())],
                timeout=restore.timeout_seconds,
                check=True,
            )
            if output.is_file():
                os.replace(str(output), str(staging))
    except (
        BotoCoreError,
        ClientError,
        OSError,
        ValueError,
        subprocess.SubprocessError,
        SystemExit,
    ) as exc:
        logger.warning(
            "CTest cost restoration unavailable; continuing with cold scheduling: %s", exc
        )
        # A worker failure must not let the parent install a partially written file.
        return 1 if args else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
