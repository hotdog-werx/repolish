from pathlib import Path
from textwrap import dedent

from repolish.config import RepolishConfig
from repolish.cookiecutter import build_final_providers


def test_config_level_provenance(tmp_path: Path):
    # Create a provider that requests deletion of 'a.txt'
    d = tmp_path / 'prov0'
    d.mkdir()
    (d / 'repolish.py').write_text(
        dedent("""
        delete_files = ['a.txt']
    """),
    )

    cfg = RepolishConfig.model_validate(
        {
            'directories': [str(d)],
            'context': {},
            'anchors': {},
            'post_process': [],
            # config negates a.txt and adds b.txt
            'delete_files': ['!a.txt', 'b.txt'],
        },
    )
    # set a config file path so provenance records the source
    cfg.config_file = tmp_path / 'repolish.yaml'

    providers = build_final_providers(cfg)

    # Final delete_files should include b.txt but not a.txt
    got = {Path(p) for p in providers.delete_files}
    assert Path('b.txt') in got
    assert Path('a.txt') not in got

    # Provenance: last decision for a.txt must be from the config and be 'keep'
    a_hist = providers.delete_history.get('a.txt')
    assert a_hist
    assert len(a_hist) >= 1
    assert a_hist[-1].source == cfg.config_file.as_posix()
    assert a_hist[-1].action.value == 'keep'

    # Provenance: last decision for b.txt must be from the config and be 'delete'
    b_hist = providers.delete_history.get('b.txt')
    assert b_hist
    assert len(b_hist) >= 1
    assert b_hist[-1].source == cfg.config_file.as_posix()
    assert b_hist[-1].action.value == 'delete'
