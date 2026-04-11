from dataclasses import dataclass
from pathlib import Path

import pytest

from repolish.scaffold.generator import generate


@dataclass
class NameCase:
    name: str
    repo_name: str
    package_name: str
    short_prefix: str
    class_name: str
    context_class: str
    inputs_class: str


@pytest.mark.parametrize(
    'case',
    [
        NameCase(
            name='hyphenated',
            repo_name='devkit-workspace',
            package_name='devkit_workspace',
            short_prefix='Workspace',
            class_name='WorkspaceProvider',
            context_class='WorkspaceProviderContext',
            inputs_class='WorkspaceProviderInputs',
        ),
        NameCase(
            name='single_word',
            repo_name='mytools',
            package_name='mytools',
            short_prefix='Mytools',
            class_name='MytoolsProvider',
            context_class='MytoolsProviderContext',
            inputs_class='MytoolsProviderInputs',
        ),
        NameCase(
            name='multi_segment',
            repo_name='org-infra-base',
            package_name='org_infra_base',
            short_prefix='Base',
            class_name='BaseProvider',
            context_class='BaseProviderContext',
            inputs_class='BaseProviderInputs',
        ),
        NameCase(
            name='acronym_suffix',
            repo_name='devkit-iac',
            package_name='devkit_iac',
            short_prefix='Iac',
            class_name='IacProvider',
            context_class='IacProviderContext',
            inputs_class='IacProviderInputs',
        ),
    ],
    ids=lambda c: c.name,
)
def test_generate_renders_names_into_files(
    tmp_path: Path,
    case: NameCase,
) -> None:
    """generate() derives all class names from the repo name and injects them into templates."""
    written = generate(case.package_name, tmp_path, simple=False)

    assert written  # at least one file must be created

    # resources/templates/repolish.py uses package_name and class_name
    entry = tmp_path / case.package_name / 'resources' / 'templates' / 'repolish.py'
    assert entry.exists()
    content = entry.read_text()
    assert case.package_name in content
    assert case.class_name in content

    # models.py uses context_class and inputs_class
    models_py = tmp_path / case.package_name / 'repolish' / 'models.py'
    assert models_py.exists()
    models_text = models_py.read_text()
    assert 'BaseInputs' in models_text
    assert case.context_class in models_text
    assert case.inputs_class in models_text

    # provider/__init__.py uses absolute imports and all three class names
    provider_init = tmp_path / case.package_name / 'repolish' / 'provider' / '__init__.py'
    provider_text = provider_init.read_text()
    assert f'from {case.package_name}.repolish.models import' in provider_text
    assert case.class_name in provider_text
    assert case.context_class in provider_text
    assert case.inputs_class in provider_text

    # __init__.py exports provider, context, and inputs
    init_py = tmp_path / case.package_name / 'repolish' / '__init__.py'
    init_text = init_py.read_text()
    assert f'from {case.package_name}.repolish.provider import' in init_text
    assert f'from {case.package_name}.repolish.models import' in init_text
    assert case.context_class in init_text
    assert case.inputs_class in init_text

    # README.md uses the cli form
    readme = tmp_path / 'README.md'
    assert readme.exists()
    assert f'cli: {case.repo_name}-link' in readme.read_text()

    # pyproject.toml uses repo_name, package_name, and declares the link script
    pyproject = tmp_path / 'pyproject.toml'
    assert pyproject.exists()
    pyproject_text = pyproject.read_text()
    assert case.repo_name in pyproject_text
    assert case.package_name in pyproject_text
    assert f'{case.repo_name}-link' in pyproject_text
    assert f'{case.package_name}.repolish.linker:main' in pyproject_text


def test_generate_package_dir_uses_package_name(tmp_path: Path) -> None:
    """The 'package/' template prefix is replaced with the actual package name."""
    generate('my_provider', tmp_path, simple=False)

    # none of the output paths should have a literal 'package' directory
    for path in tmp_path.rglob('*'):
        assert path.parts[len(tmp_path.parts)] != 'package'

    # the package directory exists under the correct name
    assert (tmp_path / 'my_provider').is_dir()
    assert (tmp_path / 'my_provider' / 'repolish' / 'provider' / '__init__.py').exists()
    assert (tmp_path / 'my_provider' / 'resources' / 'templates' / 'repolish.py').exists()


def test_generate_creates_all_expected_files(tmp_path: Path) -> None:
    """generate() in simple mode writes the expected flat file set."""
    written = generate('acme_base', tmp_path)

    relative = {p.relative_to(tmp_path).as_posix() for p in written}
    expected = {
        'README.md',
        'pyproject.toml',
        'repolish.yaml',
        'acme_base/__init__.py',
        'acme_base/py.typed',
        'acme_base/repolish/__init__.py',
        'acme_base/repolish/linker.py',
        'acme_base/repolish/models.py',
        'acme_base/repolish/provider.py',
        'acme_base/resources/templates/repolish.py',
        'acme_base/resources/templates/repolish/.gitkeep',
    }
    assert relative == expected


def test_generate_creates_all_expected_files_monorepo(tmp_path: Path) -> None:
    """generate() in monorepo mode writes the full mode-handler file set."""
    written = generate('acme_base', tmp_path, simple=False)

    relative = {p.relative_to(tmp_path).as_posix() for p in written}
    expected = {
        'README.md',
        'pyproject.toml',
        'repolish.yaml',
        'acme_base/__init__.py',
        'acme_base/py.typed',
        'acme_base/repolish/__init__.py',
        'acme_base/repolish/linker.py',
        'acme_base/repolish/models.py',
        'acme_base/repolish/provider/__init__.py',
        'acme_base/repolish/provider/root.py',
        'acme_base/repolish/provider/member.py',
        'acme_base/repolish/provider/standalone.py',
        'acme_base/resources/templates/repolish.py',
        'acme_base/resources/templates/repolish/.gitkeep',
    }
    assert relative == expected


def test_generate_skips_existing_files(tmp_path: Path) -> None:
    """Files that already exist are silently skipped; only new ones are returned."""
    # pre-create one file with sentinel content
    (tmp_path / 'README.md').write_text('sentinel', encoding='utf-8')

    written = generate('acme_base', tmp_path)

    written_names = {p.relative_to(tmp_path).as_posix() for p in written}
    assert 'README.md' not in written_names
    assert (tmp_path / 'README.md').read_text() == 'sentinel'


def test_generate_is_idempotent(tmp_path: Path) -> None:
    """Running generate() twice returns an empty list on the second run."""
    generate('acme_base', tmp_path)
    second_run = generate('acme_base', tmp_path)
    assert second_run == []


def test_generate_provider_py_contains_all_methods(tmp_path: Path) -> None:
    """The monorepo scaffold contains all Provider and ModeHandler stubs."""
    generate('my_lib', tmp_path, simple=False)
    provider_dir = tmp_path / 'my_lib' / 'repolish' / 'provider'

    # provider/__init__.py has Provider-level methods and registers mode handlers
    init_text = (provider_dir / '__init__.py').read_text()
    for method in (
        'create_context',
        'provide_inputs',
        'finalize_context',
        'get_inputs_schema',
        'create_file_mappings',
        'create_anchors',
        'create_default_symlinks',
    ):
        assert method in init_text
    assert 'LibRootHandler' in init_text
    assert 'LibMemberHandler' in init_text
    assert 'LibStandaloneHandler' in init_text
    assert 'from repolish import' in init_text
    assert 'override' in init_text
    assert 'BaseInputs' in init_text
    assert 'from my_lib.repolish.models import' in init_text
    assert 'LibProviderContext' in init_text
    assert 'LibProviderInputs' in init_text

    # each mode handler file has all ModeHandler method stubs
    for mode_file in ('root.py', 'member.py', 'standalone.py'):
        text = (provider_dir / mode_file).read_text()
        for method in (
            'provide_inputs',
            'finalize_context',
            'create_file_mappings',
            'create_anchors',
            'create_default_symlinks',
        ):
            assert method in text
        assert 'ModeHandler' in text
        assert 'LibProviderContext' in text
        assert 'LibProviderInputs' in text


def test_generate_normalizes_underscores_to_dashes_in_repo_name(
    tmp_path: Path,
) -> None:
    """Passing underscores in the name normalizes repo_name to dashes for the CLI script key."""
    generate('devkit_zensical', tmp_path)
    pyproject = (tmp_path / 'pyproject.toml').read_text()
    # script key must use dashes, not underscores
    assert 'devkit-zensical-link' in pyproject
    assert 'devkit_zensical-link' not in pyproject
