#!/bin/bash

ref=${1:-master}
curl -fsSL "https://raw.githubusercontent.com/hotdog-werx/codeguide/$ref/_install.sh" | bash -s -- "$ref"
