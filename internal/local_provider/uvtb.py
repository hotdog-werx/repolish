"""uv-toolbox environment discovery.

Temporary home alongside mise_tasks: moves to a shared provider once a
workspace provider can serve the tooling setup across repos.
"""

import shutil
import subprocess
from pathlib import Path

_SITE_PACKAGES_CMD = 'import sysconfig; print(sysconfig.get_path("purelib"))'


def env_site_packages(env: str, root: Path) -> Path:
    """Return *env*'s site-packages directory in the uv-toolbox layout.

    uvtb resolves the content-addressed venv for *env*; asking it (rather
    than guessing paths) stays correct as environments re-lock.
    """
    uvtb_bin = shutil.which('uvtb')
    if uvtb_bin is None:
        msg = f'uvtb not found on PATH; cannot resolve env {env!r} for {root}'
        raise RuntimeError(msg)
    proc = subprocess.run(  # noqa: S603 - fixed argv, binary resolved via shutil.which
        [
            uvtb_bin,
            'exec',
            '--env',
            env,
            '--',
            'python3',
            '-c',
            _SITE_PACKAGES_CMD,
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        msg = f'uvtb exec --env {env} failed in {root}: {proc.stderr.strip()}'
        raise RuntimeError(msg)
    return Path(proc.stdout.strip())
