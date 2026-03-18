import pytest
from pytest_mock import MockerFixture

from repolish.config.models import RepolishConfigFile
from repolish.linker.health import ProviderReadinessResult


@pytest.fixture(autouse=True)
def _patch_apply_infrastructure(mocker: MockerFixture) -> None:
    """Patch provider-registration infrastructure so unit tests don't touch the filesystem.

    `load_config_file` is called first in `commands/apply.command` to extract
    provider metadata for `ensure_providers_ready`; both are patched here so
    tests that only mock `load_config` don't crash on an empty / missing file.
    """
    mocker.patch(
        'repolish.commands.apply.command.load_config_file',
        return_value=RepolishConfigFile(),
    )
    mocker.patch(
        'repolish.commands.apply.command.ensure_providers_ready',
        return_value=ProviderReadinessResult(ready=[], failed=[]),
    )
