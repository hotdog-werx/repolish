"""The provider entry record passed to provider hooks.

`ProviderEntry` lives in its own leaf module so both the provider model layer
and the session-bundle model layer can reference it without an import cycle:
`models/files.py` (the `SessionBundle`) exposes the registry on the bundle,
while `models/provider.py` re-exports the class for the hooks that receive it.
"""

from typing import Any

from pydantic import BaseModel, Field


# `ProviderEntry` is the object passed to provider hooks such as
# `provide_inputs` and `finalize_context`.  it carries richer metadata
# than the former 3-tuple and uses concise names:
#
# `provider_id` (str) - unique loader-assigned identifier
# `alias` (str|None) - name under which the provider was registered in the
#     configuration; usually a directory name or config key
# `inst_type` (type|None) - concrete type of the provider instance
# `context` (object) - raw context value, usually a `BaseModel` or dict
# `context_type` (type|None) - class of `context` when it is a
#     `BaseModel`
# `input_type` (type|None) - schema returned by
#     :meth:`Provider.get_inputs_schema` (`None` for providers without inputs)
#
# Only the first and last fields are commonly used; the others exist for
# introspection and tooling.  tuple-like compatibility helpers were removed
# long ago, so callers should access attributes directly.
class ProviderEntry(BaseModel):
    """Metadata for a provider exposed during orchestration.

    `ProviderEntry` replaces the legacy 3-tuple representation.  Fields are
    intentionally named to make their purpose obvious and are short enough to
    be convenient when used in provider hooks.

    Attributes:
    ----------
    provider_id:
        unique identifier (usually the filesystem path) assigned by the loader.
    alias:
        configuration alias (the key/name used in the repolish.yaml or the
        directory name).  this may differ from `name` when providers
        override their own internal name.
    inst_type:
        the concrete `type` of the provider instance, if any.  this allows
        consumers to dispatch based on implementation class rather than string
        names.
    context:
        raw context object produced or stored for this provider.
    context_type:
        if `context` is a :class:`pydantic.BaseModel`, this is its class
        object; otherwise `None`.
    input_type:
        the schema returned by :meth:`Provider.get_inputs_schema`, equivalent
        to the third element of the old tuple.  `None` for providers that do
        not accept inputs.
    """

    provider_id: str
    # alias as specified in the project configuration file.  for
    # providers created via `create_providers` this will typically equal
    # the directory name or the config key; in many cases it is identical to
    # `provider_id` but having a separate field makes intent clear.
    alias: str | None = None
    inst_type: type[Any] | None = None
    context: object = Field(default_factory=dict)
    context_type: type[BaseModel] | None = None
    input_type: type[BaseModel] | None = None
