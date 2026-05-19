"""Object-store backend (S3/R2) for Buildkite artifact handling.

Replaces Buildkite's native artifact handling with backend choice (S3/R2),
providing functions to list, upload, and download objects with retry logic.

Backends
--------
Both use boto3's S3-compatible data path:
  S3 — IAM role on the CI agent; no explicit credentials needed.
  R2 — S3-compatible credentials stored in SSM (access key ID + secret).
       No Cloudflare SDK needed — boto3 talks directly to the R2 S3 endpoint.

Config resolution
-----------------
    env var (ARTIFACTS_*) → SSM parameter → default
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import ClientError


# ---------------------------------------------------------------------------
# Timeout / retry constants
# ---------------------------------------------------------------------------
READ_TIMEOUT = 300  # 5 minutes — fail fast instead of hanging 40+ minutes
CONNECT_TIMEOUT = 60  # 1 minute
MAX_RETRIES = 10
BACKOFF_BASE = 5  # seconds; doubles each retry
BACKOFF_CAP = 60  # 1 minute max sleep between retries

# ---------------------------------------------------------------------------
# SSM parameter paths
# ---------------------------------------------------------------------------
BACKEND_SSM_PARAM = "/services/buildkite/config/artifacts/object-store/backend"
DESTINATION_SSM_PARAM = "/services/buildkite/config/artifacts/object-store/destination"
ENDPOINT_URL_SSM_PARAM = (
    "/services/buildkite/config/artifacts/object-store/endpoint-url"
)
R2_ACCOUNT_ID_SSM_PARAM = (
    "/services/buildkite/config/artifacts/object-store/r2/account-id"
)
R2_ACCESS_KEY_ID_SSM_PARAM = (
    "/services/buildkite/config/artifacts/object-store/r2/access-key-id"
)
R2_SECRET_ACCESS_KEY_SSM_PARAM = (
    "/services/buildkite/credentials/artifacts/r2/secret-access-key"
)
ARTIFACTS_DOMAIN_SSM_PARAM = (
    "/services/buildkite/config/artifacts/object-store/r2/artifacts-domain"
)

# Prefixes that indicate a placeholder / unconfigured value rather than a real one.
_PLACEHOLDER_PREFIXES = ("SET_ME", "REPLACE_", "TODO", "CHANGEME", "FIXME")


@dataclass(frozen=True)  # frozen → safe to share across worker threads
class StoreConfig:
    """Resolved object-store backend config. Populated once by load_store_config()."""

    backend: str
    destination: str
    endpoint_url: Optional[str] = None
    r2_account_id: Optional[str] = None
    r2_access_key_id: Optional[str] = None
    r2_secret_access_key: Optional[str] = None
    artifacts_domain: Optional[str] = None


@dataclass(frozen=True)
class ObjectAuth:
    """Per-operation S3 credentials. All None for S3 (IAM role handles auth).
    For R2, populated from SSM-stored credentials derived from the Cloudflare API token.
    """

    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None


@dataclass(frozen=True)
class PublishedObject:
    bucket: str
    key: str
    url: Optional[str]
    size_bytes: int


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    size_bytes: int
    last_modified: Optional[Any] = None


def die(msg: str) -> None:
    print(f"[test-report] ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def log(msg: str) -> None:
    print(f"[test-report] {msg}", file=sys.stderr)


def _with_retry(fn, description: str):
    """Execute fn() with exponential backoff on transient errors.

    Retries up to MAX_RETRIES times. Sleep between attempts starts at BACKOFF_BASE
    seconds and doubles each time, capped at BACKOFF_CAP.

    Backoff schedule (defaults): 5 → 10 → 20 → 40 → 60 → 60 → … seconds.
    """

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            if attempt == MAX_RETRIES:
                log(f"  FAILED after {MAX_RETRIES} attempts: {description}")
                raise
            sleep = min(BACKOFF_BASE * (2 ** (attempt - 1)), BACKOFF_CAP)
            log(f"  attempt {attempt}/{MAX_RETRIES} failed for {description}: {exc}")
            log(f"  retrying in {sleep}s...")
            time.sleep(sleep)


def aws_clients():
    """Return (s3, ssm) clients for config resolution and listing only.
    Per-transfer clients are created separately in each worker thread."""

    session = boto3.session.Session()
    region_name = os.environ.get("AWS_DEFAULT_REGION", "eu-west-1")
    return (
        session.client(
            "s3", config=Config(retries={"mode": "standard", "max_attempts": 10})
        ),
        session.client(
            "ssm",
            config=Config(
                region_name=region_name,
                retries={"mode": "standard", "max_attempts": 5},
            ),
        ),
    )


def _ssm_get_optional(ssm, name: str, with_decryption: bool = True) -> Optional[str]:
    """Return SSM parameter value or None if absent. Re-raises non-NotFound errors
    so IAM misconfigurations surface explicitly."""

    try:
        return ssm.get_parameter(Name=name, WithDecryption=with_decryption)[
            "Parameter"
        ]["Value"]
    except ClientError as exc:
        response = getattr(exc, "response", {})
        code = response.get("Error", {}).get("Code")
        if code == "ParameterNotFound":
            return None
        msg = response.get("Error", {}).get("Message", str(exc))
        die(f"failed to read SSM parameter {name}: {code} — {msg}")


def _check_placeholder(value: Optional[str], label: str) -> None:
    """Die if value looks like a placeholder that was never replaced with a real one."""
    if value and any(value.startswith(prefix) for prefix in _PLACEHOLDER_PREFIXES):
        die(
            f"{label} contains placeholder value {value!r} — "
            "replace it with the real credential in Terraform tfvars or SSM"
        )


def _env_or_ssm(
    ssm, env_name: str, ssm_name: str, with_decryption: bool = True
) -> Optional[str]:
    """Env var with SSM fallback. Env takes precedence for per-job overrides."""

    return os.environ.get(env_name) or _ssm_get_optional(
        ssm, ssm_name, with_decryption=with_decryption
    )


def load_store_config(ssm) -> StoreConfig:
    """Resolve backend config: env vars → SSM → defaults.
    For R2, endpoint URL defaults to https://{account_id}.r2.cloudflarestorage.com."""

    backend = (
        (
            os.environ.get("ARTIFACTS_BACKEND")
            or _ssm_get_optional(ssm, BACKEND_SSM_PARAM)
            or "s3"
        )
        .strip()
        .lower()
    )
    if backend not in {"s3", "r2"}:
        die(
            f"unsupported artifact backend: {backend!r} (expected 's3' or 'r2'). "
            f"Check env var ARTIFACTS_BACKEND or SSM parameter {BACKEND_SSM_PARAM}"
        )

    destination = os.environ.get("ARTIFACTS_DESTINATION") or _ssm_get_optional(
        ssm, DESTINATION_SSM_PARAM
    )
    if not destination:
        die(
            "artifact destination not configured. "
            f"Set env var ARTIFACTS_DESTINATION or SSM parameter {DESTINATION_SSM_PARAM}"
        )

    endpoint_url = os.environ.get("ARTIFACTS_ENDPOINT_URL")
    artifacts_domain = os.environ.get("ARTIFACTS_DOMAIN") or _ssm_get_optional(
        ssm, ARTIFACTS_DOMAIN_SSM_PARAM
    )

    if backend == "r2":
        endpoint_url = endpoint_url or _ssm_get_optional(ssm, ENDPOINT_URL_SSM_PARAM)

        r2_account_id = _env_or_ssm(
            ssm, "ARTIFACTS_R2_ACCOUNT_ID", R2_ACCOUNT_ID_SSM_PARAM
        )
        if not r2_account_id:
            die(
                "R2 backend requires Cloudflare account ID. "
                f"Set env var ARTIFACTS_R2_ACCOUNT_ID or SSM parameter {R2_ACCOUNT_ID_SSM_PARAM}"
            )
        _check_placeholder(
            r2_account_id, f"R2 account ID (SSM {R2_ACCOUNT_ID_SSM_PARAM})"
        )

        r2_access_key_id = _env_or_ssm(
            ssm, "ARTIFACTS_R2_ACCESS_KEY_ID", R2_ACCESS_KEY_ID_SSM_PARAM
        )
        if not r2_access_key_id:
            die(
                "R2 backend requires access key ID. "
                f"Set env var ARTIFACTS_R2_ACCESS_KEY_ID or SSM parameter {R2_ACCESS_KEY_ID_SSM_PARAM}"
            )
        _check_placeholder(
            r2_access_key_id, f"R2 access key ID (SSM {R2_ACCESS_KEY_ID_SSM_PARAM})"
        )

        r2_secret_access_key = _env_or_ssm(
            ssm,
            "ARTIFACTS_R2_SECRET_ACCESS_KEY",
            R2_SECRET_ACCESS_KEY_SSM_PARAM,
            with_decryption=True,
        )
        if not r2_secret_access_key:
            die(
                "R2 backend requires secret access key. "
                f"Set env var ARTIFACTS_R2_SECRET_ACCESS_KEY or SSM SecureString {R2_SECRET_ACCESS_KEY_SSM_PARAM}"
            )
        _check_placeholder(
            r2_secret_access_key,
            f"R2 secret access key (SSM {R2_SECRET_ACCESS_KEY_SSM_PARAM})",
        )

        if not endpoint_url:
            endpoint_url = f"https://{r2_account_id}.r2.cloudflarestorage.com"

        return StoreConfig(
            backend=backend,
            destination=destination,
            endpoint_url=endpoint_url,
            r2_account_id=r2_account_id,
            r2_access_key_id=r2_access_key_id,
            r2_secret_access_key=r2_secret_access_key,
            artifacts_domain=artifacts_domain,
        )

    return StoreConfig(
        backend=backend,
        destination=destination,
        endpoint_url=endpoint_url,
        artifacts_domain=artifacts_domain,
    )


def parse_s3(uri: str) -> Tuple[str, str]:
    """Parse s3://bucket/prefix URI into (bucket, prefix).
    Also handles plain bucket names (legacy SSM format)."""

    if not uri.startswith("s3://"):
        return uri.strip("/"), ""
    parsed = urlparse(uri)
    return parsed.netloc, parsed.path.strip("/")


def key_join(*parts: str) -> str:
    """Join S3 key segments, dropping blanks to avoid double slashes."""

    return "/".join(str(part).strip("/") for part in parts if str(part).strip("/"))


def fmt_size(n: Union[int, float]) -> str:
    size = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(size) < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def resolve_object_auth(cfg: StoreConfig) -> ObjectAuth:
    """S3 → empty auth (IAM role chain). R2 → use stored S3-compatible credentials."""

    if cfg.backend == "r2":
        return ObjectAuth(
            access_key_id=cfg.r2_access_key_id,
            secret_access_key=cfg.r2_secret_access_key,
        )
    return ObjectAuth()


def _s3_client(cfg: StoreConfig, auth: ObjectAuth):
    """Create a per-thread S3 client. Called inside each worker because boto3 clients
    are not thread-safe (shared connection pool + credential state would race).

    R2 needs signature_version=s3v4 and addressing_style=path (R2 endpoints are
    account-level, not bucket-level — virtual-host style would produce invalid hostnames).
    """

    client_cfg = Config(
        read_timeout=READ_TIMEOUT,
        connect_timeout=CONNECT_TIMEOUT,
        retries={"mode": "standard", "max_attempts": 10},
    )
    if cfg.backend == "r2":
        client_cfg = Config(
            read_timeout=READ_TIMEOUT,
            connect_timeout=CONNECT_TIMEOUT,
            retries={"mode": "standard", "max_attempts": 10},
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        )

    kwargs: Dict[str, Any] = {"config": client_cfg}
    if cfg.backend == "r2":
        kwargs["region_name"] = "auto"
    if cfg.endpoint_url:
        kwargs["endpoint_url"] = cfg.endpoint_url
    if auth.access_key_id:
        kwargs["aws_access_key_id"] = auth.access_key_id
        kwargs["aws_secret_access_key"] = auth.secret_access_key

    return boto3.client("s3", **kwargs)


def internal_url(cfg: StoreConfig, key: str) -> Optional[str]:
    """Return a browser-accessible URL for an object, if artifacts_domain is set."""
    if not cfg.artifacts_domain:
        return None
    return key_join(f"https://{cfg.artifacts_domain}", key)


# Backward-compatible name for tests/spec prose that still says "public_url".
public_url = internal_url


def list_objects(
    cfg: StoreConfig,
    auth: ObjectAuth,
    bucket: str,
    prefix: str,
) -> List[ObjectInfo]:
    """List objects under an S3/R2 prefix using the configured backend."""

    def _do() -> List[ObjectInfo]:
        client = _s3_client(cfg, auth)
        paginator = client.get_paginator("list_objects_v2")
        objects: List[ObjectInfo] = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                objects.append(
                    ObjectInfo(
                        key=item["Key"],
                        size_bytes=int(item.get("Size", 0)),
                        last_modified=item.get("LastModified"),
                    )
                )
        return objects

    return _with_retry(_do, f"list s3://{bucket}/{prefix}")


def download_file(
    cfg: StoreConfig,
    auth: ObjectAuth,
    bucket: str,
    key: str,
    local_path: Path,
    *,
    concurrency: int = 32,
) -> None:
    """Download one object to a local path, creating parent directories first."""

    path = Path(local_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    def _do():
        transfer_config = TransferConfig(max_concurrency=concurrency)
        return _s3_client(cfg, auth).download_file(
            bucket, key, str(path), Config=transfer_config
        )

    _with_retry(_do, key)


def upload_file(
    cfg: StoreConfig,
    auth: ObjectAuth,
    bucket: str,
    key: str,
    local_path: Path,
    *,
    content_type: str,
    content_disposition: str,
) -> PublishedObject:
    """Upload a local file with explicit browser/download metadata."""

    path = Path(local_path)
    size_bytes = path.stat().st_size

    def _do():
        return _s3_client(cfg, auth).upload_file(
            str(path),
            bucket,
            key,
            ExtraArgs={
                "ContentType": content_type,
                "ContentDisposition": content_disposition,
            },
            Config=None,
        )

    _with_retry(_do, key)
    return PublishedObject(
        bucket=bucket,
        key=key,
        url=internal_url(cfg, key),
        size_bytes=size_bytes,
    )


def put_json(
    cfg: StoreConfig,
    auth: ObjectAuth,
    bucket: str,
    key: str,
    payload: dict,
) -> PublishedObject:
    """Serialize and upload JSON with application/json metadata."""

    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def _do():
        return _s3_client(cfg, auth).put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
            ContentDisposition="inline",
        )

    _with_retry(_do, key)
    return PublishedObject(
        bucket=bucket,
        key=key,
        url=internal_url(cfg, key),
        size_bytes=len(body),
    )
