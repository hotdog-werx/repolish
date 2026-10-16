#!/usr/bin/env bash
set -euo pipefail

# VERSION must be provided via environment variable
if [ -z "${VERSION:-}" ]; then
  echo "ERROR: VERSION must be set in environment" >&2
  exit 1
fi

# IS_RELEASE should be set (default to false if not)
IS_RELEASE="${IS_RELEASE:-false}"

# PYPI_TOKEN must be set in environment
if [ -z "${PYPI_TOKEN:-}" ]; then
  echo "ERROR: PYPI_TOKEN must be set in environment" >&2
  exit 1
fi

echo "Publishing version: ${VERSION} (IS_RELEASE: ${IS_RELEASE})"

# Only publish if this is an actual release
if [ "${IS_RELEASE}" != "true" ]; then
  echo "WARNING: IS_RELEASE is not 'true', skipping publish"
  exit 0
fi

# Publish to PyPI
echo "Publishing to PyPI..."
export UV_PUBLISH_USERNAME=__token__
export UV_PUBLISH_PASSWORD="${PYPI_TOKEN}"
uv publish

echo "Publish complete: v${VERSION} is now on PyPI"
