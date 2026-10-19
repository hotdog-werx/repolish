"""Lane CLI for the project-local provider.

`provider_cli` builds one subcommand per fast lane plus an `all` subcommand
for the provider's full pass. `provider_root` resolves against the working
directory, so run this from the project root.
"""

from pathlib import Path

from local_provider.provider import LocalProvider
from repolish.fastlane import provider_cli

main = provider_cli(LocalProvider, provider_root=Path('internal/templates'))
