"""Integration tests for repolish.pkginfo.

Each test installs a fake package into a temporary directory that is
temporarily inserted into sys.path.  This exercises the real
importlib.metadata machinery — no mocking — which is the only reliable
way to validate namespace-package detection across Python versions.

Fake package anatomy:
- The directory tree lives in ``tmp_path``.
- A ``.dist-info`` directory provides the distribution metadata.
- ``top_level.txt`` controls whether the package appears in
  ``packages_distributions()``.  Leaving it absent (editable-install
  cases) forces the ``direct_url.json`` fallback path.
- ``direct_url.json`` in the dist-info triggers the
  ``_project_from_direct_url`` fallback.
"""

import importlib
import json
import sys
from collections.abc import Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from repolish.pkginfo import resolve_package_identity


@dataclass
class TCase:
    """Describes one fake-package scenario."""

    name: str
    package_attr: str
    expected_module: str
    expected_project: str

    dist_name: str

    # Relative paths to create as empty files inside tmp_path.
    pkg_files: list[str] = field(default_factory=list)

    # Content for dist-info/top_level.txt.  None = do not write the file,
    # which causes the package to be absent from packages_distributions().
    top_level_txt: str | None = None

    # If True, write a direct_url.json pointing at tmp_path.
    use_direct_url: bool = False


def _write_dist_info(dist_dir: Path, tcase: TCase, tmp_path: Path) -> None:
    """Write METADATA and optional top_level.txt / direct_url.json into *dist_dir*."""
    (dist_dir / 'METADATA').write_text(
        f'Metadata-Version: 2.1\nName: {tcase.dist_name}\nVersion: 0.1.0\n',
        encoding='utf-8',
    )
    if tcase.top_level_txt is not None:
        (dist_dir / 'top_level.txt').write_text(
            tcase.top_level_txt + '\n',
            encoding='utf-8',
        )
    if tcase.use_direct_url:
        url = f'file://{tmp_path.as_posix()}'
        (dist_dir / 'direct_url.json').write_text(
            json.dumps({'url': url}),
            encoding='utf-8',
        )


def _evict_modules(top_mod: str) -> None:
    """Remove *top_mod* and all its submodules from sys.modules."""
    if not top_mod:
        return
    for key in list(sys.modules):
        if key == top_mod or key.startswith(f'{top_mod}.'):
            del sys.modules[key]


@contextmanager
def _fake_install(tmp_path: Path, tcase: TCase) -> Generator[None, None, None]:
    """Write a fake package into *tmp_path* and temporarily put it on sys.path.

    All changes to sys.path and sys.modules are reversed in the finally block
    so that subsequent tests start from a clean state.
    """
    for rel in tcase.pkg_files:
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text('', encoding='utf-8')

    safe_dist_name = tcase.dist_name.replace('-', '_')
    dist_dir = tmp_path / f'{safe_dist_name}-0.1.0.dist-info'
    dist_dir.mkdir()
    _write_dist_info(dist_dir, tcase, tmp_path)

    path_str = str(tmp_path)
    top_mod = tcase.pkg_files[0].split('/')[0] if tcase.pkg_files else ''
    sys.path.insert(0, path_str)
    importlib.invalidate_caches()

    try:
        yield
    finally:
        with suppress(ValueError):
            sys.path.remove(path_str)
        _evict_modules(top_mod)
        importlib.invalidate_caches()


@pytest.mark.parametrize(
    'tcase',
    [
        TCase(
            name='flat_regular',
            package_attr='rptest_flat',
            expected_module='rptest_flat',
            expected_project='rptest-flat',
            dist_name='rptest-flat',
            pkg_files=['rptest_flat/__init__.py'],
            top_level_txt='rptest_flat',
        ),
        TCase(
            name='namespace_regular',
            # rptest_ns/ has NO __init__.py → namespace; rptest_ns/inner/ has one
            package_attr='rptest_ns.inner',
            expected_module='rptest_ns.inner',
            expected_project='rptest-ns-inner',
            dist_name='rptest-ns-inner',
            pkg_files=['rptest_ns/inner/__init__.py'],
            top_level_txt='rptest_ns',
        ),
        TCase(
            name='namespace_deep_caller',
            # Caller is inside rptest_ns2.core.repolish (a sub-subpackage).
            # The function should walk down and stop at rptest_ns2.core because
            # that is the first level with an __init__.py.
            package_attr='rptest_ns2.core.repolish',
            expected_module='rptest_ns2.core',
            expected_project='rptest-ns2-core',
            dist_name='rptest-ns2-core',
            pkg_files=[
                'rptest_ns2/core/__init__.py',
                'rptest_ns2/core/repolish/__init__.py',
            ],
            top_level_txt='rptest_ns2',
        ),
        TCase(
            name='flat_editable_fallback',
            # No top_level.txt → absent from packages_distributions().
            # direct_url.json triggers the fallback resolver.
            package_attr='rptest_ed',
            expected_module='rptest_ed',
            expected_project='rptest-ed',
            dist_name='rptest-ed',
            pkg_files=['rptest_ed/__init__.py'],
            top_level_txt=None,
            use_direct_url=True,
        ),
        TCase(
            name='namespace_editable_fallback',
            # Namespace package, also absent from packages_distributions().
            package_attr='rptest_edns.pkg',
            expected_module='rptest_edns.pkg',
            expected_project='rptest-edns-pkg',
            dist_name='rptest-edns-pkg',
            pkg_files=['rptest_edns/pkg/__init__.py'],
            top_level_txt=None,
            use_direct_url=True,
        ),
        TCase(
            name='no_distribution_match',
            # Package is importable but has no usable distribution metadata:
            # no top_level.txt, no RECORD .py entries, no direct_url.json.
            # project_name should be empty.
            package_attr='rptest_nodist',
            expected_module='rptest_nodist',
            expected_project='',
            dist_name='rptest-nodist',
            pkg_files=['rptest_nodist/__init__.py'],
            top_level_txt=None,
            use_direct_url=False,
        ),
    ],
    ids=lambda c: c.name,
)
def test_resolve_package_identity(tmp_path: Path, tcase: TCase) -> None:
    """resolve_package_identity returns the correct (module_name, project_name)."""
    with _fake_install(tmp_path, tcase):
        module_name, project_name = resolve_package_identity(tcase.package_attr)

    assert module_name == tcase.expected_module
    assert project_name == tcase.expected_project


def test_namespace_with_no_real_subpackage_returns_package_attr(
    tmp_path: Path,
) -> None:
    """When all levels are namespaces/unresolvable, _resolve_module_name falls back.

    Exercises the final ``return package_attr`` in ``_resolve_module_name``:
    the namespace root exists (no ``__init__.py``) so the walk starts, but
    the sub-package ``nowhere`` does not exist at all, so the loop exhausts
    and returns the full dotted name unchanged.
    """
    # Create an empty namespace root (directory with no __init__.py).
    (tmp_path / 'rptest_orphan').mkdir()

    path_str = str(tmp_path)
    sys.path.insert(0, path_str)
    importlib.invalidate_caches()
    try:
        module_name, project_name = resolve_package_identity(
            'rptest_orphan.nowhere',
        )
    finally:
        with suppress(ValueError):
            sys.path.remove(path_str)
        _evict_modules('rptest_orphan')
        importlib.invalidate_caches()

    assert module_name == 'rptest_orphan.nowhere'
    assert project_name == ''


def test_unknown_top_level_falls_back_gracefully() -> None:
    """Unknown top-level (find_spec returns None) → module_name = top_level, project = ''.

    Exercises the ``spec is None`` short-circuit branch of
    ``_is_namespace_top_level`` (returns False when find_spec finds nothing).
    """
    # No fake install needed: the name does not exist anywhere on sys.path.
    module_name, project_name = resolve_package_identity(
        'rptest_truly_unknown.sub',
    )
    assert module_name == 'rptest_truly_unknown'
    assert project_name == ''


def test_find_spec_exception_is_caught_gracefully() -> None:
    """``_safe_find_spec`` catches ValueError/ModuleNotFoundError and returns None.

    ``find_spec('')`` raises ``ValueError: Empty module name``.  A dotted
    package_attr whose first segment is an empty string (the ``.sub`` edge
    case) reaches that code path and must not propagate the exception.
    """
    # '.sub'.split('.') → ['', 'sub']; top_level = '' → find_spec('') raises ValueError.
    module_name, project_name = resolve_package_identity('.sub')
    # Both come back empty — the name is meaningless, but it must not raise.
    assert module_name == ''
    assert project_name == ''


def test_packages_distributions_exception_is_caught(
    mocker: MockerFixture,
) -> None:
    """``_project_from_distributions`` swallows exceptions from importlib.metadata.

    If ``packages_distributions()`` raises (e.g. due to a corrupt dist-info),
    the function logs at DEBUG and returns '' so the caller can attempt the
    direct-URL fallback.
    """
    mocker.patch(
        'repolish.pkginfo.packages_distributions',
        side_effect=RuntimeError('metadata scan failed'),
    )
    # Falls through to _project_from_direct_url which returns '' too because
    # 'rptest_truly_unknown' is not importable.
    module_name, project_name = resolve_package_identity('rptest_truly_unknown')
    assert module_name == 'rptest_truly_unknown'
    assert project_name == ''


def test_importable_package_with_no_matching_distribution(
    tmp_path: Path,
) -> None:
    """``_project_from_direct_url`` exhausts all distributions and returns ''.

    The package is importable (on sys.path, has __init__.py) but its dist-info
    carries no direct_url.json, so ``_source_path_from_dist`` returns None for
    every distribution and the final ``return ''`` is reached.
    """
    tcase = TCase(
        name='norep',
        package_attr='rptest_norep',
        expected_module='rptest_norep',
        expected_project='',
        dist_name='rptest-norep',
        pkg_files=['rptest_norep/__init__.py'],
        # No top_level.txt → absent from packages_distributions.
        # No direct_url.json → _source_path_from_dist returns None for this dist.
        top_level_txt=None,
        use_direct_url=False,
    )
    with _fake_install(tmp_path, tcase):
        module_name, project_name = resolve_package_identity(tcase.package_attr)

    assert module_name == 'rptest_norep'
    assert project_name == ''


def test_returns_empty_tuple() -> None:
    """Empty string | None → ('', '')."""
    assert resolve_package_identity('') == ('', '')
    assert resolve_package_identity(None) == ('', '')


def test_submodule_attr_for_flat_package(tmp_path: Path) -> None:
    """A dotted __package__ inside a flat package resolves to the top-level name.

    e.g. ``__package__ = 'mypkg.utils'`` where ``mypkg/__init__.py`` exists
    (regular package, not a namespace) → module_name should be ``'mypkg'``.
    """
    tcase = TCase(
        name='flat_submodule',
        package_attr='rptest_flatdeep.utils',
        expected_module='rptest_flatdeep',
        expected_project='rptest-flatdeep',
        dist_name='rptest-flatdeep',
        pkg_files=[
            'rptest_flatdeep/__init__.py',
            'rptest_flatdeep/utils/__init__.py',
        ],
        top_level_txt='rptest_flatdeep',
    )
    with _fake_install(tmp_path, tcase):
        module_name, project_name = resolve_package_identity(tcase.package_attr)

    assert module_name == tcase.expected_module
    assert project_name == tcase.expected_project
