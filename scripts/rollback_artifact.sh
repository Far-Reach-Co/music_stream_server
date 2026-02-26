#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/_common.sh"

SERVICE_NAME="${MUSIC_SERVICE_NAME:-radio.service}"
TARGET_RELEASE="${1:-previous}"

echo "Rolling back on $SERVER ..."
"${SSH_CMD[@]}" \
  "RELEASES_DIR='$RELEASES_DIR' CURRENT_LINK='$CURRENT_LINK' SERVICE_NAME='$SERVICE_NAME' TARGET_RELEASE='$TARGET_RELEASE' bash -se" <<'REMOTE'
set -euo pipefail

if [[ ! -d "$RELEASES_DIR" ]]; then
  echo "No releases directory found: $RELEASES_DIR"
  exit 1
fi

mapfile -t releases < <(find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d -print | sort)
count="${#releases[@]}"
if (( count == 0 )); then
  echo "No releases available."
  exit 1
fi

if [[ "$TARGET_RELEASE" == "previous" ]]; then
  if (( count < 2 )); then
    echo "Need at least 2 releases for previous rollback."
    exit 1
  fi
  target="${releases[count-2]}"
else
  target="${RELEASES_DIR}/${TARGET_RELEASE}"
  if [[ ! -d "$target" ]]; then
    echo "Release not found: $target"
    exit 1
  fi
fi

ln -sfn "$target" "$CURRENT_LINK"
systemctl restart "$SERVICE_NAME"

echo "Rollback complete. Current release:"
readlink -f "$CURRENT_LINK"
systemctl --no-pager --full status "$SERVICE_NAME" | sed -n '1,24p'
REMOTE
