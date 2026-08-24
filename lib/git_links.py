from __future__ import annotations

from urllib.parse import urlparse


def build_commit_url(repo: str | None, commit: str | None) -> str | None:
    """Build a browser URL for a git commit from Buildkite repo metadata."""
    if not repo or not commit:
        return None

    repo = repo.strip()
    commit = commit.strip()
    if not repo or not commit:
        return None

    normalized = _normalize_repo_url(repo)
    if normalized is None:
        return None

    host, path = normalized
    commit_path = "commit" if host == "github.com" else "-/commit"
    return f"https://{host}/{path}/{commit_path}/{commit}"


def _normalize_repo_url(repo: str) -> tuple[str, str] | None:
    if repo.startswith("git@") and ":" in repo:
        host, path = repo.removeprefix("git@").split(":", 1)
        return _clean_host_path(host, path)

    parsed = urlparse(repo)
    if parsed.scheme in {"http", "https", "ssh", "git"} and parsed.netloc:
        return _clean_host_path(parsed.netloc, parsed.path.lstrip("/"))

    return None


def _clean_host_path(host: str, path: str) -> tuple[str, str] | None:
    host = host.strip().lower()
    path = path.strip().rstrip("/")
    path = path.removesuffix(".git")
    if not host or not path or "/" not in path:
        return None
    return host, path
