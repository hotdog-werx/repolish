import builtins
import importlib
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

import pytest
from pytest_mock import MockerFixture

from repolish.loader.module import get_module
from tests.support import module_name_from_path, write_module


class PatchSysPath(Protocol):
    def __call__(
        self,
        tmp_path: Path,
        *,
        include: bool = True,
    ) -> None:  # pragma: no cover
        ...


@pytest.fixture
def patch_sys_path(mocker: MockerFixture) -> PatchSysPath:
    """Fixture returning a helper to patch `sys.path`.

    The returned callable accepts `tmp_path` and an `include` flag with
    the same semantics as the former `_patch_sys_path` helper.  By
    providing this as a fixture we can avoid passing `mocker` explicitly to
    every test that needs it.
    """

    def _inner(tmp_path: Path, *, include: bool = True) -> None:
        if include:
            new_path = [str(tmp_path)] + [p for p in sys.path if p != str(tmp_path)]
        else:
            new_path = [p for p in sys.path if str(tmp_path) not in p]
        mocker.patch.object(sys, 'path', new=new_path)

    return _inner


def test_get_module_registers_importable_name(
    tmp_path: Path,
    patch_sys_path: PatchSysPath,
) -> None:
    """Loading a file under a package registers it by its dotted name.

    This exercises the public entry point `get_module` instead of the
    implementation helpers.  When the file lives inside a directory that
    appears on `sys.path` we expect the loader to register the module under
    its guessed import name so that a subsequent `importlib.import_module`
    call returns the same object rather than re-executing the source.

    The test patches `sys.path` rather than mutating it so that the
    fixture takes care of restoring the original list when the test exits.
    """
    # create a three-level package with a module inside.  the helper
    # ensures all parent directories are packages.
    src = tmp_path / 'codeguide' / 'resources' / 'templates' / 'repolish.py'
    write_module(src, 'value = 123\n', root=tmp_path)

    # make the tmp directory importable and exercise the normal path
    patch_sys_path(tmp_path, include=True)

    mod_dict = get_module(str(src))
    assert mod_dict['value'] == 123

    # compute expected import name using helper instead of duplicating logic
    expected_name = module_name_from_path(src, tmp_path)
    imported = importlib.import_module(expected_name)
    assert imported.__dict__ is mod_dict


def test_get_module_reuses_existing_module(
    tmp_path: Path,
    patch_sys_path: PatchSysPath,
) -> None:
    """If a module is already imported, `get_module` returns its globals.

    Importing the file by name first simulates the usual case for a
    package that's already installed.  The loader shouldn't create a second
    synthetic module entry, and the returned dictionary must be identical to
    the one on the already-imported module object.

    Instead of modifying `sys.path` directly we patch it so the fixture
    restores the original value automatically.  This matches the style used
    in subsequent tests.
    """
    src = tmp_path / 'mod.py'
    write_module(src, 'x = 1\n', root=tmp_path)

    patch_sys_path(tmp_path, include=True)

    # import the module normally so it populates sys.modules
    imported = importlib.import_module('mod')

    mod_dict = get_module(str(src))
    assert mod_dict is imported.__dict__

    # no synthetic modules should have been created during the call
    assert not any(k.startswith('repolish_module_') for k in sys.modules)


def test_get_module_fallback_synthetic(
    tmp_path: Path,
    patch_sys_path: PatchSysPath,
) -> None:
    """When the path isn't importable, we still load the file with a safe name.

    The synthetic entry uses a prefix so we can locate it later.  Calling
    `get_module` twice should return the same dictionary since the module is
    now present in `sys.modules` by its synthetic name.
    """
    src = tmp_path / 'somefile.py'
    write_module(src, 'y = 2\n', root=tmp_path)

    # ensure our temporary directory is *not* on sys.path so import guessing
    # will fail and we exercise the fallback branch.
    patch_sys_path(tmp_path, include=False)

    mod_dict = get_module(str(src))
    assert mod_dict['y'] == 2

    # because `import_name` is None the loader does *not* register the
    # synthetic name in `sys.modules`; this keeps the global module cache
    # unpolluted.  the helper therefore returns a fresh module on every call.
    synth_keys = [k for k in sys.modules if k.startswith('repolish_module_')]
    assert not synth_keys

    # repeated loading creates a new module object (not the same dict)
    assert get_module(str(src)) is not mod_dict


def test_get_module_import_fallback_on_bad_import(
    tmp_path: Path,
    mocker: MockerFixture,
    patch_sys_path: PatchSysPath,
) -> None:
    """If importing the guessed name fails, we still load via fallback.

    Patch `builtins.__import__` to raise `ImportError` for the specific
    module name that `_guess_import_name` returns.  The call should succeed
    and register the module under that name (exercising both the exception
    branch in `_try_imported_module` and the registration path in
    ``_load_module_from_path``).
    """
    src = tmp_path / 'pkg' / 'repolish.py'
    write_module(src, 'v = 7\n', root=tmp_path)

    # make the guessable package path available for the loader
    patch_sys_path(tmp_path, include=True)

    # compute the guessed name so the patch knows when to raise
    guess = '.'.join(Path(str(src)).relative_to(tmp_path).with_suffix('').parts)

    # create a temporary module cache without the guessed name and patch
    # it onto ``sys``.  this way the test can freely modify ``sys.modules``
    # without affecting the real global state; pytest-mock will restore the
    # original dictionary when the test completes.
    temp_mods = {k: v for k, v in sys.modules.items() if k != guess}
    mocker.patch.object(sys, 'modules', temp_mods)

    real_import = builtins.__import__

    def fake_import(
        name: str,
        globs: Mapping[str, object] | None = None,
        locs: Mapping[str, object] | None = None,
        fromlist: Sequence[str] | None = (),
        level: int = 0,
    ) -> object:
        if name == guess:
            # if the importer attempted to add the module, remove it before
            # signalling failure so the fallback registration will fire
            sys.modules.pop(name, None)
            msg = 'simulated failure'
            raise ImportError(msg)
        return real_import(name, globs, locs, fromlist, level)

    mocker.patch.object(builtins, '__import__', side_effect=fake_import)

    mod_dict = get_module(str(src))
    assert mod_dict['v'] == 7

    # import_name should now be registered because fallback was used
    assert guess in sys.modules


def test_get_module_errors(tmp_path: Path):
    """Verify `get_module` raises for invalid paths.

    Two failure modes are covered:
    * a non-`.py` extension triggers an `ImportError` (guess helper path),
    * a completely missing file raises `FileNotFoundError`.
    """
    # case 1 - wrong extension
    src = tmp_path / 'foo.txt'
    src.write_text('z = 99\n')
    with pytest.raises(ImportError):
        get_module(str(src))

    # case 2 - file missing at all
    with pytest.raises(FileNotFoundError):
        get_module(str(tmp_path / 'does_not_exist.py'))
