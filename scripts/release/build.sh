#!/usr/bin/env bash
set -euo pipefail

# VERSION must be provided via environment variable
if [ -z "${VERSION:-}" ]; then
  echo "ERROR: VERSION must be set in environment" >&2
  exit 1
fi

# IS_RELEASE should be set (default to false if not)
IS_RELEASE="${IS_RELEASE:-false}"

echo "Building version: ${VERSION} (IS_RELEASE: ${IS_RELEASE})"

# Clean previous build artifacts to avoid stale files
if [ -d dist ]; then
  echo "Cleaning previous build artifacts..."
  rm -rf dist
fi

# Set version with hatch
# This is now handled by releez
# echo "Setting version with hatch..."
# uvx hatch version "${VERSION}"

# Build the package
echo "Building package..."
uv build --no-sources

echo "Build complete: dist/ contains build artifacts"
ls -lh dist/
