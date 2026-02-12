from pathlib import Path

import pytest

from repolish.config.models import ProviderInfo
from repolish.exceptions import SymlinkError
from repolish.linker.symlinks import create_additional_link, link_resources


def test_link_resources_source_not_exists(tmp_path: Path):
    """Test link_resources raises FileNotFoundError when source doesn't exist."""
    source = tmp_path / 'nonexistent'
    target = tmp_path / 'target'

    with pytest.raises(
        FileNotFoundError,
        match='Source directory does not exist',
    ):
        link_resources(source, target)


def test_link_resources_source_not_directory(tmp_path: Path):
    """Test link_resources raises SymlinkError when source is not a directory."""
    source = tmp_path / 'file.txt'
    source.write_text('content')
    target = tmp_path / 'target'

    with pytest.raises(SymlinkError, match='Source must be a directory'):
        link_resources(source, target)


def test_create_additional_link_source_not_exists(
    provider_resources_setup: Path,
    basic_provider_info: ProviderInfo,
):
    """Test create_additional_link raises when source doesn't exist."""
    with pytest.raises(FileNotFoundError, match='Source does not exist'):
        create_additional_link(
            provider_info=basic_provider_info,
            provider_name='mylib',
            source='nonexistent/file.txt',
            target='target.txt',
        )
