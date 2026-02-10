"""Shared fixtures for linker tests."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, TypedDict

import pytest
import pytest_mock

from repolish.linker.decorator import resource_linker


class PackageDictFixture(TypedDict):
    """Type for test_package fixture return value."""

    pkg_root: Path
    resources: Path


class MockedPackageDict(TypedDict):
    """Type for mocked_package fixture return value."""

    pkg_root: Path
    resources: Path
    mock_link_resources: Any


class BasicLinkCliFixture(Protocol):
    """Type for basic_link_cli fixture callable."""

    def __call__(self) -> None:
        """Execute the decorated link_cli function."""
        ...


@pytest.fixture
def test_package(tmp_path: Path):
    """Fixture that creates a basic test package structure."""
    pkg_root = tmp_path / 'mylib'
    pkg_root.mkdir()
    resources = pkg_root / 'resources'
    resources.mkdir()
    return {'pkg_root': pkg_root, 'resources': resources}


@pytest.fixture
def mocked_package(tmp_path: Path, mocker: pytest_mock.MockerFixture):
    """Fixture that sets up a mock package structure and common mocks."""
    pkg_root = tmp_path / 'mylib'
    pkg_root.mkdir()
    resources = pkg_root / 'resources'
    resources.mkdir()

    # Mock _get_package_root to return our test package
    mocker.patch(
        'repolish.linker.decorator._get_package_root',
        return_value=pkg_root,
    )

    return {
        'pkg_root': pkg_root,
        'resources': resources,
        'mock_link_resources': mocker.patch(
            'repolish.linker.decorator.link_resources',
            return_value=True,
        ),
    }


@pytest.fixture
def basic_link_cli(mocked_package: dict[str, Any]) -> Callable[[], None]:
    """Fixture that returns a basic decorated link_cli function."""

    @resource_linker(
        library_name='mylib',
        default_source_dir='resources',
    )
    def link_cli() -> None:
        pass

    return link_cli
