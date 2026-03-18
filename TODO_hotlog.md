# hotlog TODO

## Teach hotlog to serialize `pathlib.Path` objects

**Problem**: `hotlog` uses PyYAML under the hood to format structured log
events. When a log call includes a `Path` value (e.g. `root_dir` from
`MonorepoContext`), PyYAML raises:

```
yaml.representer.RepresenterError: ('cannot represent an object', PosixPath('…'))
```

**Fix**: Register a custom YAML representer for `pathlib.Path` (and
`pathlib.PurePath`) that emits the path as a plain string.

```python
import pathlib
import yaml

def _represent_path(dumper: yaml.Dumper, data: pathlib.PurePath) -> yaml.Node:
    return dumper.represent_str(data.as_posix())

yaml.add_representer(pathlib.PurePath, _represent_path)
yaml.add_multi_representer(pathlib.PurePath, _represent_path)
```

Adding this (or equivalent) in hotlog's internal YAML setup would make all
downstream callers (repolish, etc.) safe to log `Path` values without
pre-conversion.

**Where to look in hotlog**: the module that configures the YAML dumper /
formatter — likely something like `hotlog/_formatter.py` or wherever `yaml.dump`
/ `yaml.safe_dump` is called.

**Workaround in the meantime**: convert `Path` values to strings before passing
them to log calls, or override `model_dump` / use `model_dump(mode='json')` for
Pydantic models that contain `Path` fields before logging.
