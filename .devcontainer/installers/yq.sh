#!/bin/bash
set -xeuo pipefail

yqVersion=4.45.1
arch=$(python -c 'import platform; print("arm64" if platform.machine() in ["aarch64", "arm64"] else "amd64")')

curl -fsSL "https://github.com/mikefarah/yq/releases/download/v${yqVersion}/yq_linux_${arch}" -o /usr/bin/yq
chmod +x /usr/bin/yq
