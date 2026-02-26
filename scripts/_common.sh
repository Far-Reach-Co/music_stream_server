#!/bin/bash
set -euo pipefail

SERVER="${MUSIC_SERVER:-root@165.227.88.65}"
REMOTE_DIR="${MUSIC_REMOTE_DIR:-/root/music_stream_server}"
DEPLOY_ROOT="${MUSIC_DEPLOY_ROOT:-$REMOTE_DIR}"
RELEASES_DIR="${DEPLOY_ROOT}/releases"
CURRENT_LINK="${DEPLOY_ROOT}/current"
ARTIFACTS_DIR="${DEPLOY_ROOT}/artifacts"
SSH_KEY="${MUSIC_SSH_KEY:-}"
BRANCH="${MUSIC_BRANCH:-main}"
REPO_URL="${MUSIC_REPO_URL:-https://github.com/Far-Reach-Co/music_stream_server.git}"

if [[ -n "$SSH_KEY" ]]; then
  SSH_CMD=(ssh -i "$SSH_KEY" "$SERVER")
  SCP_CMD=(scp -i "$SSH_KEY")
else
  SSH_CMD=(ssh "$SERVER")
  SCP_CMD=(scp)
fi

run_remote() {
  "${SSH_CMD[@]}" "$1"
}

run_service_action() {
  local service="$1"
  local action="$2"

  case "$action" in
    restart)
      run_remote "systemctl restart $service && systemctl status $service --no-pager --full"
      ;;
    status)
      run_remote "systemctl status $service --no-pager --full"
      ;;
    logs)
      run_remote "journalctl -u $service --no-pager -n 120"
      ;;
    stop)
      run_remote "systemctl stop $service && echo '$service stopped'"
      ;;
    *)
      echo "Usage: $0 {restart|status|logs|stop}"
      exit 1
      ;;
  esac
}
