from __future__ import annotations

import subprocess
from typing import Any

import pytest

from repolish.providers import get_owner_repo


def test_get_owner_repo_from_this_repository() -> None:
    """Test that get_owner_repo() correctly parses the repolish repository."""
    owner, repo = get_owner_repo()

    # This test is running in the repolish repository
    assert owner == 'hotdog-werx'
    assert repo == 'repolish'


def test_get_owner_repo_tuple_unpacking() -> None:
    """Test that get_owner_repo() returns a tuple that can be unpacked."""
    result = get_owner_repo()

    # Should be a tuple of exactly 2 elements
    assert isinstance(result, tuple)
    assert len(result) == 2

    owner, repo = result
    assert isinstance(owner, str)
    assert isinstance(repo, str)
    assert owner  # Should not be empty
    assert repo  # Should not be empty


def test_get_owner_repo_with_invalid_remote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that get_owner_repo() raises ValueError for invalid remote URLs."""

    def mock_check_output(*args: Any, **kwargs: Any) -> str:
        return 'https://example.com/not-a-github-url\n'

    monkeypatch.setattr(subprocess, 'check_output', mock_check_output)

    with pytest.raises(
        ValueError,
        match='No owner/repo found in git remote URL',
    ):
        get_owner_repo()


@pytest.mark.parametrize(
    'url',
    [
        'https://github.com/test-owner/test-repo.git\n',
        'git@github.com:test-owner/test-repo.git\n',
        'https://github.com/test-owner/test-repo\n',
        'https://token@github.com/test-owner/test-repo.git\n',
    ],
)
def test_get_owner_repo_various_urls(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    """Test parsing various GitHub URL formats."""

    def mock_check_output(*args: Any, **kwargs: Any) -> str:
        return url

    monkeypatch.setattr(subprocess, 'check_output', mock_check_output)

    owner, repo = get_owner_repo()
    assert owner == 'test-owner'
    assert repo == 'test-repo'
