#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

APP_NAME="${APP_NAME:-music_stream_server}"
DIST_DIR="${DIST_DIR:-$REPO_ROOT/dist}"
RELEASE_ID="${RELEASE_ID:-$(date +%Y%m%d%H%M%S)}"
STAGE_DIR="$DIST_DIR/${APP_NAME}_${RELEASE_ID}"
ARTIFACT_PATH="$DIST_DIR/${APP_NAME}_${RELEASE_ID}.tar.gz"

mkdir -p "$DIST_DIR"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"

# Build a clean payload without VCS/venv/cache content.
rsync -a "$REPO_ROOT/" "$STAGE_DIR/" \
  --exclude '.git/' \
  --exclude '.DS_Store' \
  --exclude '__pycache__/' \
  --exclude 'venv/' \
  --exclude '.env' \
  --exclude 'dist/' \
  --exclude '*.pyc'

if command -v git >/dev/null 2>&1 && git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  GIT_COMMIT="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
else
  GIT_COMMIT="unknown"
fi

cat > "$STAGE_DIR/BUILD_INFO" <<EOF
app_name=$APP_NAME
release_id=$RELEASE_ID
built_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
git_commit=$GIT_COMMIT
EOF

tar -C "$DIST_DIR" -czf "$ARTIFACT_PATH" "${APP_NAME}_${RELEASE_ID}"
rm -rf "$STAGE_DIR"

echo "$ARTIFACT_PATH"
