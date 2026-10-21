"""Bootstrap: make the internal provider tree importable in these tests.

`internal-tools` is deliberately not a dev dependency (the repo floor is
3.11 while it requires 3.12), so the tests path-bootstrap the package the
same way tests/test_pkginfo.py does for scratch trees.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
