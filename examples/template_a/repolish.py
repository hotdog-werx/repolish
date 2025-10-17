def create_context() -> dict[str, str]:
    """Return the cookiecutter context for the example template.

    This is intentionally small for the example.
    """
    return {'package_name': 'project'} # git can use used to figure out repo name


def create_delete_files() -> list[str]:
    """Return a list of POSIX-style paths the provider proposes to delete."""
    return ['old_file.txt']


def create_anchors() -> dict[str, str]:
    """Return example anchor replacements used by the example provider."""
    return {'extra-deps': '\nrequests = "^2.30"\n'}

