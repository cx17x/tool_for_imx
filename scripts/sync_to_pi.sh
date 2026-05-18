#!/usr/bin/env bash
set -euo pipefail

PI_HOST="${PI_HOST:-192.168.1.108}"
PI_USER="${PI_USER:-pi}"
PI_PORT="${PI_PORT:-22}"
PI_DIR="${PI_DIR:-/home/${PI_USER}/tool_for_imx}"
PI_VENV_DIR="${PI_VENV_DIR:-/home/${PI_USER}/venv}"
PI_MODEL_PATH="${PI_MODEL_PATH:-/home/qwerty/q_imx_model/rpk_out/network.rpk}"
PI_LABELS_PATH="${PI_LABELS_PATH:-/home/qwerty/q_imx_model/labels.txt}"

INSTALL_SERVICES=0
RESTART_SERVICES=0

usage() {
  cat <<EOF
Usage: $0 [--install-services] [--restart-services]

Environment variables:
  PI_HOST  Raspberry Pi host or IP. Default: 192.168.1.108
  PI_USER  SSH user. Default: pi
  PI_PORT  SSH port. Default: 22
  PI_DIR   Remote project directory. Default: /home/\${PI_USER}/tool_for_imx
  PI_VENV_DIR Remote Python venv. Default: /home/\${PI_USER}/venv
  PI_MODEL_PATH Remote IMX500 model path.
  PI_LABELS_PATH Remote labels path.

Examples:
  $0
  PI_USER=qwerty $0
  PI_USER=pi PI_DIR=/home/pi/tool_for_imx $0 --install-services
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-services)
      INSTALL_SERVICES=1
      shift
      ;;
    --restart-services)
      RESTART_SERVICES=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

cd "$(dirname "$0")/.."

case "$PI_DIR" in
  "/"|"/home"|"/home/"|"/home/${PI_USER}"|"/home/${PI_USER}/")
    echo "Refusing to sync to unsafe PI_DIR: $PI_DIR" >&2
    exit 2
    ;;
esac

REMOTE="${PI_USER}@${PI_HOST}"
SSH=(ssh -p "$PI_PORT")
SSH_TTY=(ssh -tt -p "$PI_PORT")
RSYNC=(rsync -az --delete -e "ssh -p $PI_PORT")

echo "Sync target: ${REMOTE}:${PI_DIR}"

"${SSH[@]}" "$REMOTE" "mkdir -p '$PI_DIR'"

"${RSYNC[@]}" \
  --exclude ".git/" \
  --exclude "__pycache__/" \
  --exclude "*.pyc" \
  --exclude ".DS_Store" \
  --exclude "_transfer_work/" \
  --exclude "web_dashboard/static/hls/" \
  ./ "${REMOTE}:${PI_DIR}/"

echo "Project synced."

if [[ "$INSTALL_SERVICES" -eq 1 ]]; then
  echo "Installing systemd services on Raspberry Pi..."
  "${SSH_TTY[@]}" "$REMOTE" "cd '$PI_DIR' && PROJECT_DIR='$PI_DIR' SERVICE_USER='$PI_USER' VENV_DIR='$PI_VENV_DIR' MODEL_PATH='$PI_MODEL_PATH' LABELS_PATH='$PI_LABELS_PATH' ./scripts/install_systemd_services.sh"
fi

if [[ "$RESTART_SERVICES" -eq 1 ]]; then
  echo "Restarting active IMX services on Raspberry Pi..."
  "${SSH_TTY[@]}" "$REMOTE" "sudo systemctl try-restart imx-object-detection.service imx-object-detection-video.service imx-web-dashboard.service imx-bbox-receiver.service"
fi

echo "Done."
