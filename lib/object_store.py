from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:  # boto3 is installed by the plugin venv in Buildkite; keep unit tests lightweight.
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
except ModuleNotFoundError:  # pragma: no cover - exercised only when optional deps are absent.
    boto3 = None  # type: ignore[assignment]
    Config = None  # type: ignore[assignment]

    class ClientError(Exception):  # type: ignore[no-redef]
        pass


READ_TIMEOUT = 300
CONNECT_TIMEOUT = 60
MAX_RETRIES = 10
BACKOFF_BASE = 5
BACKOFF_CAP = 60

BACKEND_SSM_PARAM = "/services/buildkite/config/artifacts/object-store/backend"
DESTINATION_SSM_PARAM = "/services/buildkite/config/artifacts/object-store/destination"
ENDPOINT_URL_SSM_PARAM = "/services/buildkite/config/artifacts/object-store/endpoint-url"
R2_ACCOUNT_ID_SSM_PARAM = "/services/buildkite/config/artifacts/object-store/r2/account-id"
R2_ACCESS_KEY_ID_SSM_PARAM = "/services/buildkite/config/artifacts/object-store/r2/access-key-id"
R2_SECRET_ACCESS_KEY_SSM_PARAM = "/services/buildkite/credentials/artifacts/r2/secret-access-key"
ARTIFACTS_DOMAIN_SSM_PARAM = "/services/buildkite/config/artifacts/object-store/r2/artifacts-domain"

_PLACEHOLDER_PREFIXES = ("SET_ME", "REPLACE_", "TODO", "CHANGEME", "FIXME")


@dataclass(frozen=True)
class StoreConfig:
    """Resolved S3/R2 object-store backend configuration."""

    backend: str
    destination: str
    endpoint_url: str | None = None
    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    artifacts_domain: str | None = None


@dataclass(frozen=True)
class ObjectAuth:
    """Per-operation object-store credentials.

    Empty credentials mean the normal AWS credential/IAM role chain is used. R2
    operations use explicit S3-compatible access keys resolved from env/SSM.
    """

    access_key_id: str | None = None
    secret_access_key: str | None = None


@dataclass(frozen=True)
class PublishedObject:
    bucket: str
    key: str
    url: str | None
    size_bytes: int


def die(msg: str) -> None:
    print(f"[test-report] ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def log(msg: str) -> None:
    print(f"[test-report] {msg}", file=sys.stderr)


def _require_boto3() -> None:
    if boto3 is None or Config is None:
        die("boto3/botocore are required for object-store operations; run hooks/post-checkout or install lib/requirements.txt")


def _with_retry(fn, description: str):
    """Execute fn() with exponential backoff for transient object-store errors."""

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
    """Return (s3, ssm) clients for config resolution and listing."""

    _require_boto3()
    session = boto3.session.Session()
    region_name = os.environ.get("AWS_DEFAULT_REGION", "eu-west-1")
    return (
        session.client("s3", config=Config(retries={"mode": "standard", "max_attempts": 10})),
        session.client(
            "ssm",
            config=Config(
                region_name=region_name,
                retries={"mode": "standard", "max_attempts": 5},
            ),
        ),
    )


def _ssm_get_optional(ssm, name: str, with_decryption: bool = True) -> str | None:
    """Return SSM parameter value or None if absent."""

    try:
        return ssm.get_parameter(Name=name, WithDecryption=with_decryption)["Parameter"]["Value"]
    except ClientError as exc:
        response = getattr(exc, "response", {})
        code = response.get("Error", {}).get("Code")
        if code == "ParameterNotFound":
            return None
        msg = response.get("Error", {}).get("Message", str(exc))
        die(f"failed to read SSM parameter {name}: {code} — {msg}")


def _check_placeholder(value: str | None, label: str) -> None:
    if value and any(value.startswith(prefix) for prefix in _PLACEHOLDER_PREFIXES):
        die(
            f"{label} contains placeholder value {value!r} — "
            "replace it with the real credential in Terraform tfvars or SSM"
        )


def _env_or_ssm(ssm, env_name: str, ssm_name: str, with_decryption: bool = True) -> str | None:
    """Read env var with SSM fallback. Env takes precedence for per-job overrides."""

    return os.environ.get(env_name) or _ssm_get_optional(ssm, ssm_name, with_decryption=with_decryption)


def load_store_config(ssm) -> StoreConfig:
    """Resolve backend config from ARTIFACTS_* env vars, SSM, and defaults."""

    backend = (
        (os.environ.get("ARTIFACTS_BACKEND") or _ssm_get_optional(ssm, BACKEND_SSM_PARAM) or "s3")
        .strip()
        .lower()
    )
    if backend not in {"s3", "r2"}:
        die(
            f"unsupported artifact backend: {backend!r} (expected 's3' or 'r2'). "
            f"Check env var ARTIFACTS_BACKEND or SSM parameter {BACKEND_SSM_PARAM}"
        )

    destination = os.environ.get("ARTIFACTS_DESTINATION") or _ssm_get_optional(ssm, DESTINATION_SSM_PARAM)
    if not destination:
        die(
            "artifact destination not configured. "
            f"Set env var ARTIFACTS_DESTINATION or SSM parameter {DESTINATION_SSM_PARAM}"
        )

    endpoint_url = os.environ.get("ARTIFACTS_ENDPOINT_URL")
    artifacts_domain = os.environ.get("ARTIFACTS_DOMAIN") or _ssm_get_optional(ssm, ARTIFACTS_DOMAIN_SSM_PARAM)

    if backend == "r2":
        endpoint_url = endpoint_url or _ssm_get_optional(ssm, ENDPOINT_URL_SSM_PARAM)

        r2_account_id = _env_or_ssm(ssm, "ARTIFACTS_R2_ACCOUNT_ID", R2_ACCOUNT_ID_SSM_PARAM)
        if not r2_account_id:
            die(
                "R2 backend requires Cloudflare account ID. "
                f"Set env var ARTIFACTS_R2_ACCOUNT_ID or SSM parameter {R2_ACCOUNT_ID_SSM_PARAM}"
            )
        _check_placeholder(r2_account_id, f"R2 account ID (SSM {R2_ACCOUNT_ID_SSM_PARAM})")

        r2_access_key_id = _env_or_ssm(ssm, "ARTIFACTS_R2_ACCESS_KEY_ID", R2_ACCESS_KEY_ID_SSM_PARAM)
        if not r2_access_key_id:
            die(
                "R2 backend requires access key ID. "
                f"Set env var ARTIFACTS_R2_ACCESS_KEY_ID or SSM parameter {R2_ACCESS_KEY_ID_SSM_PARAM}"
            )
        _check_placeholder(r2_access_key_id, f"R2 access key ID (SSM {R2_ACCESS_KEY_ID_SSM_PARAM})")

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


def parse_s3(uri: str) -> tuple[str, str]:
    """Parse s3://bucket/prefix into (bucket, prefix); plain names are buckets."""

    if not uri.startswith("s3://"):
        return uri.strip("/"), ""
    parsed = urlparse(uri)
    return parsed.netloc, parsed.path.strip("/")


def key_join(*parts: str) -> str:
    """Join URL/S3 key segments, dropping blanks and duplicate slashes."""

    return "/".join(str(part).strip("/") for part in parts if str(part).strip("/"))


def fmt_size(n: int | float) -> str:
    size = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(size) < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def resolve_object_auth(ssm, cfg: StoreConfig, permission: str) -> ObjectAuth:
    """S3 uses ambient AWS auth; R2 uses resolved S3-compatible credentials."""

    if cfg.backend == "r2":
        return ObjectAuth(
            access_key_id=cfg.r2_access_key_id,
            secret_access_key=cfg.r2_secret_access_key,
        )
    return ObjectAuth()


def _s3_client(cfg: StoreConfig, auth: ObjectAuth):
    """Create an S3 client for one operation/thread."""

    _require_boto3()
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

    kwargs: dict[str, Any] = {"config": client_cfg}
    if cfg.backend == "r2":
        kwargs["region_name"] = "auto"
    if cfg.endpoint_url:
        kwargs["endpoint_url"] = cfg.endpoint_url
    if auth.access_key_id:
        kwargs["aws_access_key_id"] = auth.access_key_id
        kwargs["aws_secret_access_key"] = auth.secret_access_key

    return boto3.client("s3", **kwargs)


def internal_url(cfg: StoreConfig, key: str) -> str | None:
    if not cfg.artifacts_domain:
        return None
    return key_join(f"https://{cfg.artifacts_domain}", key)


# Backward-compatible name for tests/spec prose that still says "public_url".
public_url = internal_url


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
