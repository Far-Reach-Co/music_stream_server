#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Building artifact..."
artifact="$("$SCRIPT_DIR/build_artifact.sh")"
echo "Built: $artifact"

echo "Deploying artifact..."
"$SCRIPT_DIR/deploy_artifact.sh" "$artifact"
