from git_links import build_commit_url


def test_build_commit_url_github_https_strips_dot_git():
    assert (
        build_commit_url(
            "https://github.com/acme/project.git",
            "0123456789abcdef0123456789abcdef01234567",
        )
        == "https://github.com/acme/project/commit/0123456789abcdef0123456789abcdef01234567"
    )


def test_build_commit_url_github_ssh():
    assert (
        build_commit_url(
            "git@github.com:acme/project.git",
            "0123456789abcdef0123456789abcdef01234567",
        )
        == "https://github.com/acme/project/commit/0123456789abcdef0123456789abcdef01234567"
    )


def test_build_commit_url_gitlab_https_uses_dash_commit_path():
    assert (
        build_commit_url(
            "https://gitlab.example.com/acme/project.git",
            "0123456789abcdef0123456789abcdef01234567",
        )
        == "https://gitlab.example.com/acme/project/-/commit/0123456789abcdef0123456789abcdef01234567"
    )


def test_build_commit_url_returns_none_when_metadata_is_missing():
    assert build_commit_url(None, "0123456789abcdef0123456789abcdef01234567") is None
    assert build_commit_url("https://github.com/acme/project.git", None) is None
    assert build_commit_url("", "0123456789abcdef0123456789abcdef01234567") is None
    assert build_commit_url("https://github.com/acme/project.git", "") is None
