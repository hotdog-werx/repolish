import pytest
from pytest_mock import MockerFixture

from repolish.config.models import RepolishConfigFile
from repolish.linker.health import ProviderReadinessResult
from repolish.loader.models import DryRunResult


@pytest.fixture(autouse=True)
def _patch_apply_infrastructure(mocker: MockerFixture) -> None:
    """Patch provider-registration infrastructure so unit tests don't touch the filesystem.

    `load_config_file` is called first in `commands/apply.command` to extract
    provider metadata for `ensure_providers_ready`; both are patched here so
    tests that only mock `load_config` don't crash on an empty / missing file.

    `create_providers` is patched to prevent the dry pass in
    `_collect_session_outputs` from trying to load real provider modules.
    """
    mocker.patch(
        'repolish.commands.apply.pipeline.load_config_file',
        return_value=RepolishConfigFile(),
    )
    mocker.patch(
        'repolish.commands.apply.pipeline.ensure_providers_ready',
        return_value=ProviderReadinessResult(ready=[], failed=[]),
    )
    mocker.patch(
        'repolish.commands.apply.pipeline.create_providers',
        return_value=DryRunResult(
            provider_contexts={},
            all_providers_list=[],
            emitted_inputs=[],
        ),
    )
