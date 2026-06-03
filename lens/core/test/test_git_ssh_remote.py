import pytest

from lens.core.git_ssh_remote import parse_git_ssh_remote


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("git@github.com:org/repo.git", ("github.com", 22)),
        ("git@gitlab.com:group/sub.git", ("gitlab.com", 22)),
        ("git@git.example.internal:my/repo.git", ("git.example.internal", 22)),
        ("ssh://git@github.com/org/repo.git", ("github.com", 22)),
        ("ssh://git@gitlab.com/group/project.git", ("gitlab.com", 22)),
        ("ssh://git@codeberg.org/user/repo.git", ("codeberg.org", 22)),
        ("ssh://git@git.server.example:2222/repo.git", ("git.server.example", 2222)),
        ("git@[2001:db8::1]:repo.git", ("2001:db8::1", 22)),
        ("ssh://git@[2001:db8::1]/repo.git", ("2001:db8::1", 22)),
        ("ssh://git@[2001:db8::1]:2222/repo.git", ("2001:db8::1", 2222)),
    ],
)
def test_parse_git_ssh_remote_ok(url: str, expected: tuple[str, int]) -> None:
    assert parse_git_ssh_remote(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "https://github.com/org/repo.git",
        "http://gitlab.com/group/repo.git",
        "file:///tmp/repo",
        "git://github.com/org/repo.git",
        "not-a-remote",
        "github.com:org/repo.git",
    ],
)
def test_parse_git_ssh_remote_rejects(url: str) -> None:
    with pytest.raises(ValueError):
        parse_git_ssh_remote(url)
