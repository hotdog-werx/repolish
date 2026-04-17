"""Link CLI for simple_provider.

Registered as the `simple-provider-link` console script.  When called
with ``--info`` it prints the ProviderInfo JSON; when called without
flags it links the package resources into ``.repolish/simple-provider/``.

Resources layout (relative to this package):
    resources/             ← linked as a whole into the project
    resources/templates/   ← provider_root; contains repolish.py and templates
"""

from repolish.linker import resource_linker_cli

main = resource_linker_cli()
