#!/usr/bin/env bash
set -euo pipefail

ROOT="${BOOKOASIS_UPDATE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)}"
SERVICE_USER="${BOOKOASIS_UPDATE_USER:-$(id -un)}"
SERVICE_GROUP="$(id -gn "$SERVICE_USER")"
WORKER_DIR="${BOOKOASIS_UPDATE_WORKER_DIR:-/home/$SERVICE_USER/.local/lib/bookoasis}"
WORKER_PATH="$WORKER_DIR/host_update_worker.py"
UNIT_PATH="/etc/systemd/system/bookoasis-github-updater.service"
TEMP_UNIT="$(mktemp)"
trap 'rm -f "$TEMP_UNIT"' EXIT

if [[ ! -f "$ROOT/docker-compose.yml" || ! -d "$ROOT/logs" ]]; then
  echo "BookOasis Compose 경로와 logs 폴더를 확인할 수 없습니다: $ROOT" >&2
  exit 1
fi
if [[ ! -f "$(dirname "${BASH_SOURCE[0]}")/bookoasis_host_updater.py" ]]; then
  echo "호스트 업데이트 작업 파일을 찾을 수 없습니다." >&2
  exit 1
fi

mkdir -p "$ROOT/.codex-updates"
install -d -m 0750 "$WORKER_DIR"
install -m 0750 "$(dirname "${BASH_SOURCE[0]}")/bookoasis_host_updater.py" "$WORKER_PATH"

cat > "$TEMP_UNIT" <<EOF
[Unit]
Description=BookOasis GitHub Update Worker
After=docker.service
Wants=docker.service

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
SupplementaryGroups=docker
WorkingDirectory=$ROOT
Environment=BOOKOASIS_UPDATE_ROOT=$ROOT
Environment=BOOKOASIS_UPDATE_WORKER_PATH=$WORKER_PATH
ExecStart=/usr/bin/python3 $WORKER_PATH --watch
Restart=always
RestartSec=3
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=full
ReadWritePaths=$ROOT/logs $ROOT/.codex-updates $WORKER_DIR
UMask=0027

[Install]
WantedBy=multi-user.target
EOF

sudo install -o root -g root -m 0644 "$TEMP_UNIT" "$UNIT_PATH"
sudo systemctl daemon-reload
sudo systemctl enable --now bookoasis-github-updater.service
sudo systemctl --no-pager --full status bookoasis-github-updater.service
