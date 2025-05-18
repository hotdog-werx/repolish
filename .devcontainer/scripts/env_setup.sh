
#!/bin/bash
set -euox pipefail

./codeguide.sh master
symlinks.sh
