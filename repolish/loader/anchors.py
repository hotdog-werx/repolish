from .context import call_factory_with_context, extract_from_module_dict
from .module import get_module


def process_anchors(
    module_dict: dict[str, object],
    merged_context: dict[str, object],
    merged_anchors: dict[str, str],
) -> None:
    """Resolve anchors for a provider module and merge into `merged_anchors`.

    Accepts either a callable `create_anchors()` or a module-level `anchors`
    variable. If a callable is provided it will be invoked with the merged
    context and must return a `dict`.
    """
    anchors_fact = module_dict.get('create_anchors') or module_dict.get(
        'anchors',
    )
    if callable(anchors_fact):
        val = call_factory_with_context(anchors_fact, merged_context)
        if val is None:
            return
        if not isinstance(val, dict):
            msg = 'create_anchors() must return a dict'
            raise TypeError(msg)
        merged_anchors.update(val)
    elif isinstance(anchors_fact, dict):
        merged_anchors.update(anchors_fact)


def extract_anchors_from_module(
    module: str | dict[str, object],
) -> dict[str, str]:
    """Extract anchors mapping from a template module (path or dict).

    Supports either a callable `create_anchors()` or a module-level `anchors` dict.
    Returns an empty dict on failure.
    """
    module_dict = module if isinstance(module, dict) else get_module(str(module))
    anchors = extract_from_module_dict(
        module_dict,
        'create_anchors',
        expected_type=dict,
    )
    if isinstance(anchors, dict):
        return anchors
    a_obj = extract_from_module_dict(
        module_dict,
        'anchors',
        expected_type=dict,
        allow_callable=False,
    )
    if isinstance(a_obj, dict):
        return a_obj
    # Absence of anchors is fine; return empty mapping
    return {}
