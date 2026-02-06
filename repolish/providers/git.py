"""Git utilities for providers.

This module provides functions to extract information from the current
git repository, such as the repository owner and name.
"""

import re
import subprocess


def get_owner_repo() -> tuple[str, str]:
    """Get the owner and repository name from the git remote URL.

    Parses the git remote 'origin' URL to extract the repository owner
    and name. Supports both HTTPS and SSH URL formats for GitHub.

    Returns:
        A tuple containing (owner, repo_name).

    Raises:
        ValueError: If the git remote URL cannot be parsed or no owner/repo
            information is found.

    Examples:
        >>> owner, repo = get_owner_repo()
        >>> print(f"{owner}/{repo}")
        hotdog-werx/repolish
    """
    git_remote = subprocess.check_output(
        ['git', 'remote', 'get-url', 'origin'],  # noqa: S607
        text=True,
    ).strip()

    match = re.search(
        r'(?:https://(?:[^/]+@)?github\.com/|git@github\.com:)([^/]+)/([^.]+)(?:\.git)?$',
        git_remote,
    )
    if match:
        owner, repo = match.groups()
        return owner, repo

    msg = f'No owner/repo found in git remote URL: {git_remote}'
    raise ValueError(msg)
