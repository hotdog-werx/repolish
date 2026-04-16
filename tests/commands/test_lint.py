from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

import pytest

from repolish.commands.lint import command


@dataclass
class LintCase:
    name: str
    repolish_py: str
    templates: dict[str, str]
    expected_exit_code: int


_CLASS_PROVIDER_BASE = dedent("""\
    from pydantic import BaseModel, Field
    from repolish import BaseContext, Provider, BaseInputs

    class Ctx(BaseContext):
        package_name: str = 'my-project'
        version: str = '0.1.0'

    class MyProvider(Provider[Ctx, BaseInputs]):
        def create_context(self) -> Ctx:
            return Ctx(package_name='test-pkg')
""")

_MODULE_PROVIDER = dedent("""\
    def create_context():
        return {'package_name': 'my-project', 'version': '0.1.0'}
""")


def _make_provider(tmp_path: Path, src: str, templates: dict[str, str]) -> Path:
    provider_dir = tmp_path / 'provider'
    provider_dir.mkdir()
    (provider_dir / 'repolish.py').write_text(src, encoding='utf-8')
    tpl_root = provider_dir / 'repolish'
    tpl_root.mkdir()
    for name, content in templates.items():
        path = tpl_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    return provider_dir


@pytest.mark.parametrize(
    'case',
    [
        LintCase(
            name='clean_all_known_variables',
            repolish_py=_CLASS_PROVIDER_BASE,
            templates={'README.md': '# {{ package_name }} v{{ version }}\n'},
            expected_exit_code=0,
        ),
        LintCase(
            name='unknown_root_variable',
            repolish_py=_CLASS_PROVIDER_BASE,
            templates={'README.md': '# {{ unknown_var }}\n'},
            expected_exit_code=1,
        ),
        LintCase(
            name='invalid_deep_access_on_nested_model',
            repolish_py=dedent("""\
                from pydantic import BaseModel, Field
                from repolish import BaseContext, Provider, BaseInputs

                class Meta(BaseModel):
                    owner: str = 'acme'

                class Ctx(BaseContext):
                    meta: Meta = Field(default_factory=Meta)

                class MyProvider(Provider[Ctx, BaseInputs]):
                    def create_context(self) -> Ctx:
                        return Ctx()
            """),
            templates={'out.txt': '{{ meta.nonexistent_field }}\n'},
            expected_exit_code=1,
        ),
        LintCase(
            name='valid_deep_access_on_nested_model',
            repolish_py=dedent("""\
                from pydantic import BaseModel, Field
                from repolish import BaseContext, Provider, BaseInputs

                class Meta(BaseModel):
                    owner: str = 'acme'

                class Ctx(BaseContext):
                    meta: Meta = Field(default_factory=Meta)

                class MyProvider(Provider[Ctx, BaseInputs]):
                    def create_context(self) -> Ctx:
                        return Ctx()
            """),
            templates={'out.txt': '{{ meta.owner }}\n'},
            expected_exit_code=0,
        ),
        LintCase(
            name='repolish_builtin_deep_access_valid',
            repolish_py=dedent("""\
                from repolish import BaseContext, Provider, BaseInputs

                class Ctx(BaseContext):
                    pass

                class MyProvider(Provider[Ctx, BaseInputs]):
                    def create_context(self) -> Ctx:
                        return Ctx()
            """),
            templates={
                'header.txt': 'owner={{ repolish.repo.owner }} year={{ repolish.year }}\n',
            },
            expected_exit_code=0,
        ),
        LintCase(
            name='repolish_builtin_invalid_field',
            repolish_py=dedent("""\
                from repolish import BaseContext, Provider, BaseInputs

                class Ctx(BaseContext):
                    pass

                class MyProvider(Provider[Ctx, BaseInputs]):
                    def create_context(self) -> Ctx:
                        return Ctx()
            """),
            templates={'header.txt': '{{ repolish.no_such_field }}\n'},
            expected_exit_code=1,
        ),
        LintCase(
            name='loop_variable_not_flagged_but_iterable_missing',
            repolish_py=_CLASS_PROVIDER_BASE,
            templates={
                'list.txt': '{% for item in items %}{{ item }}\n{% endfor %}\n',
            },
            expected_exit_code=1,  # 'items' is not in context
        ),
        LintCase(
            name='loop_variable_not_flagged_iterable_in_context',
            repolish_py=dedent("""\
                from repolish import BaseContext, Provider, BaseInputs
                from typing import Any

                class Ctx(BaseContext):
                    items: list[str] = ['a', 'b']

                class MyProvider(Provider[Ctx, BaseInputs]):
                    def create_context(self) -> Ctx:
                        return Ctx()
            """),
            templates={
                'list.txt': '{% for item in items %}{{ item }}\n{% endfor %}\n',
            },
            expected_exit_code=0,
        ),
        LintCase(
            name='preprocessor_directives_stripped_before_parse',
            repolish_py=_CLASS_PROVIDER_BASE,
            templates={
                'config.toml': dedent("""\
                    name = "{{ package_name }}"
                    ## repolish-start[extra]
                    # extra section
                    ## repolish-end[extra]
                    ## repolish-regex[ver]: version = "(.+)"
                    version = "0.1.0"
                """),
            },
            expected_exit_code=0,
        ),
        LintCase(
            name='non_pydantic_depth_skipped',
            # Accessing a method on a str field (str is not a BaseModel) should not
            # raise a lint error - the static pass gracefully stops at non-Pydantic types.
            repolish_py=_CLASS_PROVIDER_BASE,
            templates={'readme.md': '{{ package_name.upper() }}\n'},
            expected_exit_code=0,
        ),
        LintCase(
            name='jinja_syntax_error_in_template',
            repolish_py=_CLASS_PROVIDER_BASE,
            templates={'bad.j2': '{{ unclosed\n'},
            expected_exit_code=1,
        ),
        LintCase(
            name='optional_field_native_union_syntax',
            # Python 3.10+ `X | None` union syntax should be unwrapped correctly.
            repolish_py=dedent("""\
                from repolish import BaseContext, Provider, BaseInputs

                class Ctx(BaseContext):
                    label: str | None = None

                class MyProvider(Provider[Ctx, BaseInputs]):
                    def create_context(self) -> Ctx:
                        return Ctx(label='hi')
            """),
            templates={'out.txt': '{% if label %}{{ label }}{% endif %}\n'},
            expected_exit_code=0,
        ),
        LintCase(
            name='computed_attr_access_not_flagged',
            # obj.method().attr: the Getattr whose .node is a Call returns None
            # from _resolve_chain and is silently dropped - no false positive.
            repolish_py=_CLASS_PROVIDER_BASE,
            templates={'out.txt': '{{ package_name.strip().upper() }}\n'},
            expected_exit_code=0,
        ),
        LintCase(
            name='optional_nested_model_native_syntax_valid',
            # Native `Author | None` stores as types.UnionType on Python 3.11.
            # Dotted access through this field exercises the types.UnionType
            # branch of _unwrap_optional.
            repolish_py=dedent("""\
                from pydantic import BaseModel
                from repolish import BaseContext, Provider, BaseInputs

                class Author(BaseModel):
                    name: str = 'anon'

                class Ctx(BaseContext):
                    author: Author | None = None

                class MyProvider(Provider[Ctx, BaseInputs]):
                    def create_context(self) -> Ctx:
                        return Ctx(author=Author())
            """),
            templates={
                'out.txt': '{% if author %}{{ author.name }}{% endif %}\n',
            },
            expected_exit_code=0,
        ),
        LintCase(
            name='render_error_non_undefined',
            # {{ 1 / 0 }} parses fine but raises ZeroDivisionError at render
            # time, exercising the generic `except Exception` branch.
            repolish_py=_CLASS_PROVIDER_BASE,
            templates={'out.txt': '{{ 1 / 0 }}\n'},
            expected_exit_code=1,
        ),
        LintCase(
            name='optional_nested_model_field_access_valid',
            # Dotted access through an Optional[NestedModel] field exercises
            # _unwrap_optional via the typing.Union branch so the inner model
            # type can be inspected for the next chain segment.
            repolish_py=dedent("""\
                from typing import Optional
                from pydantic import BaseModel, Field
                from repolish import BaseContext, Provider, BaseInputs

                class Author(BaseModel):
                    name: str = 'anon'

                class Ctx(BaseContext):
                    author: Optional[Author] = None

                class MyProvider(Provider[Ctx, BaseInputs]):
                    def create_context(self) -> Ctx:
                        return Ctx(author=Author())
            """),
            templates={
                'out.txt': '{% if author %}{{ author.name }}{% endif %}\n',
            },
            expected_exit_code=0,
        ),
    ],
    ids=lambda c: c.name,
)
def test_lint_command(tmp_path: Path, case: LintCase) -> None:
    provider_dir = _make_provider(tmp_path, case.repolish_py, case.templates)
    exit_code = command(provider_dir)
    assert exit_code == case.expected_exit_code


def test_lint_missing_repolish_py(tmp_path: Path) -> None:
    provider_dir = tmp_path / 'provider'
    provider_dir.mkdir()
    (provider_dir / 'repolish').mkdir()
    assert command(provider_dir) == 1


def test_lint_missing_templates_dir(tmp_path: Path) -> None:
    provider_dir = tmp_path / 'provider'
    provider_dir.mkdir()
    (provider_dir / 'repolish.py').write_text(_CLASS_PROVIDER_BASE)
    # no repolish/ directory
    assert command(provider_dir) == 1


def test_lint_unmapped_conditional_source(tmp_path: Path) -> None:
    """A _repolish.* template not referenced in create_file_mappings triggers a warning.

    This exercises the ``if unmapped:`` block inside :func:`command` that
    reports forgotten conditional sources — template files that would be
    silently skipped during apply because they were never wired to a
    destination via ``create_file_mappings``.
    """
    provider_dir = _make_provider(
        tmp_path,
        _CLASS_PROVIDER_BASE,
        {
            # Regular template — clean, no lint issues.
            'README.md': '# {{ package_name }}\n',
            # Conditional file NOT referenced in create_file_mappings.
            '_repolish.orphan.toml': '[tool]\nname = "{{ package_name }}"\n',
            # Nested template creates a subdirectory so _unmapped_in_dir's
            # `if not item.is_file(): continue` branch is exercised.
            'sub/helper.md': '# helper\n',
        },
    )
    assert command(provider_dir) == 1


def test_lint_module_style_provider_fails_load(tmp_path: Path) -> None:
    # Module-style providers (no Provider subclass) are not supported in v1;
    # the command should report the failure and return exit code 1.
    provider_dir = _make_provider(
        tmp_path,
        _MODULE_PROVIDER,
        {'out.txt': '{{ package_name }}\n'},
    )
    assert command(provider_dir) == 1
