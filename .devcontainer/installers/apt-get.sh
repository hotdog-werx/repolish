#!/bin/bash
set -xeuo pipefail

apt-get update
apt-get install -y curl make bash-completion git-all locales libarchive-tools

locale-gen en_US.UTF-8
update-locale LANG=en_US.UTF-8

rm -rf /var/cache/apt/archives /var/lib/apt/lists
