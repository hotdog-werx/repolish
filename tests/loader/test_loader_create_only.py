from pathlib import Path
from typing import TYPE_CHECKING, cast

from repolish.loader.create_only import process_create_only_files
from repolish.loader.module_loader import inject_provider_instance_for_module

if TYPE_CHECKING:
    from repolish.loader.models import Provider as _ProviderBase


def test_process_create_only_non_iterable_returns_noop():
    # callable returns None -> no changes
    md = cast('dict[str, object]', {'create_create_only_files': lambda: None})
    inject_provider_instance_for_module(md, 'test.provider.create_only.none')
    inst = cast('_ProviderBase', md['_repolish_provider_instance'])
    s = set()
    process_create_only_files(inst, {}, s)
    assert s == set()

    # module-level not iterable
    md2 = cast('dict[str, object]', {'create_only_files': None})
    inject_provider_instance_for_module(md2, 'test.provider.create_only.none2')
    inst2 = cast('_ProviderBase', md2['_repolish_provider_instance'])
    s2 = set()
    process_create_only_files(inst2, {}, s2)
    assert s2 == set()


def test_process_create_only_handles_path_items():
    md = cast(
        'dict[str, object]',
        {'create_create_only_files': lambda: [Path('one.txt'), 'two.txt']},
    )
    inject_provider_instance_for_module(md, 'test.provider.create_only.items')
    inst = cast('_ProviderBase', md['_repolish_provider_instance'])
    s = set()
    process_create_only_files(inst, {}, s)
    assert Path('one.txt') in s
    assert Path('two.txt') in s
