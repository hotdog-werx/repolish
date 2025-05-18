#!/bin/bash
set -xeuo pipefail

bash -c "$(curl -fsSL https://raw.githubusercontent.com/ohmybash/oh-my-bash/master/tools/install.sh)"

# switch theme
sed -i 's/OSH_THEME="font"/OSH_THEME="agnoster"/' /root/.bashrc
