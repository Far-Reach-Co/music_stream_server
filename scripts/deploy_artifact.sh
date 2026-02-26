#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/_common.sh"

ARTIFACT_PATH="${1:-}"
SERVICE_NAME="${MUSIC_SERVICE_NAME:-radio.service}"
KEEP_RELEASES="${MUSIC_KEEP_RELEASES:-3}"

if [[ -z "$ARTIFACT_PATH" ]]; then
  echo "Usage: $0 <artifact.tar.gz>"
  exit 1
fi

if [[ ! -f "$ARTIFACT_PATH" ]]; then
  echo "Artifact not found: $ARTIFACT_PATH"
  exit 1
fi

ARTIFACT_ABS="$(cd "$(dirname "$ARTIFACT_PATH")" && pwd)/$(basename "$ARTIFACT_PATH")"
ARTIFACT_FILE="$(basename "$ARTIFACT_ABS")"
RELEASE_NAME="${ARTIFACT_FILE%.tar.gz}"
REMOTE_ARTIFACT_PATH="${ARTIFACTS_DIR}/${ARTIFACT_FILE}"
REMOTE_RELEASE_PATH="${RELEASES_DIR}/${RELEASE_NAME}"

echo "Ensuring remote deploy directories exist ..."
"${SSH_CMD[@]}" "mkdir -p '$DEPLOY_ROOT' '$RELEASES_DIR' '$ARTIFACTS_DIR'"

echo "Uploading $ARTIFACT_FILE to $SERVER ..."
"${SCP_CMD[@]}" "$ARTIFACT_ABS" "${SERVER}:${REMOTE_ARTIFACT_PATH}"

echo "Deploying release $RELEASE_NAME on $SERVER ..."
"${SSH_CMD[@]}" \
  "DEPLOY_ROOT='$DEPLOY_ROOT' RELEASES_DIR='$RELEASES_DIR' CURRENT_LINK='$CURRENT_LINK' ARTIFACTS_DIR='$ARTIFACTS_DIR' REMOTE_ARTIFACT_PATH='$REMOTE_ARTIFACT_PATH' REMOTE_RELEASE_PATH='$REMOTE_RELEASE_PATH' SERVICE_NAME='$SERVICE_NAME' KEEP_RELEASES='$KEEP_RELEASES' bash -se" <<'REMOTE'
set -euo pipefail

mkdir -p "$DEPLOY_ROOT" "$RELEASES_DIR" "$ARTIFACTS_DIR"
rm -rf "$REMOTE_RELEASE_PATH"
mkdir -p "$REMOTE_RELEASE_PATH"
tar -xzf "$REMOTE_ARTIFACT_PATH" -C "$REMOTE_RELEASE_PATH" --strip-components=1

cd "$REMOTE_RELEASE_PATH"
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install --no-cache-dir -r requirements.txt

if [[ -f "${DEPLOY_ROOT}/.env" ]]; then
  ln -sfn "${DEPLOY_ROOT}/.env" "${REMOTE_RELEASE_PATH}/.env"
fi

if [[ -f "${DEPLOY_ROOT}/private_frc_cloudfront_key.pem" ]]; then
  ln -sfn "${DEPLOY_ROOT}/private_frc_cloudfront_key.pem" "${REMOTE_RELEASE_PATH}/private_frc_cloudfront_key.pem"
fi

if [[ -f "${REMOTE_RELEASE_PATH}/systemd/${SERVICE_NAME}" ]]; then
  cp "${REMOTE_RELEASE_PATH}/systemd/${SERVICE_NAME}" "/etc/systemd/system/${SERVICE_NAME}"
fi

ln -sfn "$REMOTE_RELEASE_PATH" "$CURRENT_LINK"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

if [[ "$KEEP_RELEASES" =~ ^[0-9]+$ ]] && (( KEEP_RELEASES > 0 )); then
  mapfile -t old_releases < <(find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d -print | sort | head -n -"${KEEP_RELEASES}" || true)
  for rel in "${old_releases[@]}"; do
    if [[ "$rel" != "$(readlink -f "$CURRENT_LINK")" ]]; then
      rm -rf "$rel"
    fi
  done
fi

echo "Current release:"
readlink -f "$CURRENT_LINK"
systemctl --no-pager --full status "$SERVICE_NAME" | sed -n '1,24p'

health_code="000"
for i in 1 2 3 4 5 6 7 8 9 10; do
  health_code="$(curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:5000/ || true)"
  if [[ "$health_code" == "200" ]]; then
    break
  fi
  sleep 1
done

echo "health=$health_code"
if [[ "$health_code" != "200" ]]; then
  echo "Health check failed after retries."
  exit 1
fi
REMOTE

echo "Deploy complete."
