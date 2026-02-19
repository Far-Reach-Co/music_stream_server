#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/_common.sh"

echo "Deploying branch '$BRANCH' to $SERVER:$REMOTE_DIR ..."

"${SSH_CMD[@]}" \
  "REMOTE_DIR='$REMOTE_DIR' BRANCH='$BRANCH' REPO_URL='$REPO_URL' bash -se" <<'REMOTE'
set -euo pipefail

if [[ ! -d "$REMOTE_DIR/.git" ]]; then
  echo "Remote checkout missing .git. Re-cloning..."
  BACKUP_DIR="${REMOTE_DIR}_backup_$(date +%Y%m%d%H%M%S)"
  if [[ -d "$REMOTE_DIR" ]]; then
    mv "$REMOTE_DIR" "$BACKUP_DIR"
  fi
  git clone --branch "$BRANCH" --single-branch "$REPO_URL" "$REMOTE_DIR"

  if [[ -f "$BACKUP_DIR/.env" ]]; then
    cp "$BACKUP_DIR/.env" "$REMOTE_DIR/.env"
  fi
  if [[ -f "$BACKUP_DIR/private_frc_cloudfront_key.pem" ]]; then
    cp "$BACKUP_DIR/private_frc_cloudfront_key.pem" "$REMOTE_DIR/private_frc_cloudfront_key.pem"
    chmod 600 "$REMOTE_DIR/private_frc_cloudfront_key.pem"
  fi
fi

cd "$REMOTE_DIR"
git fetch origin
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

# Keep pip cache off-disk for this low-storage droplet.
python3 -m pip install --no-cache-dir -r requirements.txt

if [[ -f "$REMOTE_DIR/systemd/radio.service" ]]; then
  cp "$REMOTE_DIR/systemd/radio.service" /etc/systemd/system/radio.service
  systemctl daemon-reload
else
  echo "systemd unit file not found in repo; keeping currently installed radio.service"
fi

systemctl enable radio.service
systemctl restart radio.service

systemctl --no-pager --full status radio.service | sed -n '1,28p'
curl -sS -o /dev/null -w "health=%{http_code}\n" http://127.0.0.1:5000/
REMOTE

echo "Deploy complete."
