#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/pi/tool_for_imx}"
SERVICE_USER="${SERVICE_USER:-pi}"
VENV_DIR="${VENV_DIR:-/home/${SERVICE_USER}/venv}"
MODEL_PATH="${MODEL_PATH:-/home/qwerty/q_imx_model/rpk_out/network.rpk}"
LABELS_PATH="${LABELS_PATH:-/home/qwerty/q_imx_model/labels.txt}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
DASHBOARD_ENV_FILE="${DASHBOARD_ENV_FILE:-/etc/default/imx-web-dashboard}"
SUDOERS_FILE="${SUDOERS_FILE:-/etc/sudoers.d/imx-web-dashboard}"

cd "$(dirname "$0")/.."

install_service() {
  local source_file="$1"
  local target_file="$SYSTEMD_DIR/$(basename "$source_file")"

  sed \
    -e "s|WorkingDirectory=/home/pi/tool_for_imx|WorkingDirectory=$PROJECT_DIR|g" \
    -e "s|/home/pi/venv|$VENV_DIR|g" \
    -e "s|/home/pi/tool_for_imx|$PROJECT_DIR|g" \
    -e "s|/home/qwerty/q_imx_model/rpk_out/network.rpk|$MODEL_PATH|g" \
    -e "s|/home/qwerty/q_imx_model/labels.txt|$LABELS_PATH|g" \
    -e "s|User=pi|User=$SERVICE_USER|g" \
    "$source_file" | sudo tee "$target_file" >/dev/null

  sudo chmod 0644 "$target_file"
  echo "Installed $target_file"
}

install_service systemd/imx-object-detection.service
install_service systemd/imx-object-detection-video.service
install_service systemd/imx-bbox-receiver.service
install_service systemd/imx-web-dashboard.service

CONFIG_PATH="$PROJECT_DIR/config/object_detection.json"
if [[ -f "$CONFIG_PATH" ]]; then
  python3 - "$CONFIG_PATH" "$MODEL_PATH" "$LABELS_PATH" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
model_path = sys.argv[2]
labels_path = sys.argv[3]

config = json.loads(config_path.read_text(encoding="utf-8"))
config["model"] = model_path
config["labels"] = labels_path
config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
PY
fi

sudo chmod 0755 "$PROJECT_DIR/scripts/restart_object_detection_video.sh" 2>/dev/null || true

existing_token=""
if sudo test -f "$DASHBOARD_ENV_FILE"; then
  existing_token="$(sudo sed -n 's/^IMX_DASHBOARD_ADMIN_TOKEN=//p' "$DASHBOARD_ENV_FILE" | tail -n 1 | tr -d '\"')"
fi
if [[ -z "$existing_token" ]]; then
  if command -v openssl >/dev/null 2>&1; then
    existing_token="$(openssl rand -hex 24)"
  else
    existing_token="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
  fi
fi
{
  echo "IMX_DASHBOARD_ADMIN_TOKEN=\"$existing_token\""
} | sudo tee "$DASHBOARD_ENV_FILE" >/dev/null
sudo chmod 0640 "$DASHBOARD_ENV_FILE"

{
  echo "$SERVICE_USER ALL=(root) NOPASSWD: $PROJECT_DIR/scripts/restart_object_detection_video.sh \"\""
} | sudo tee "$SUDOERS_FILE" >/dev/null
sudo chmod 0440 "$SUDOERS_FILE"
sudo visudo -cf "$SUDOERS_FILE" >/dev/null

sudo systemctl daemon-reload

echo
echo "Installed systemd services."
echo "Python venv: $VENV_DIR"
echo "Model path: $MODEL_PATH"
echo "Labels path: $LABELS_PATH"
echo "Dashboard admin token: $existing_token"
echo "Enable one object-detection service, not both:"
echo "  sudo systemctl enable --now imx-object-detection.service"
echo "  sudo systemctl enable --now imx-object-detection-video.service"
echo
echo "Optional debug receiver:"
echo "  sudo systemctl enable --now imx-bbox-receiver.service"
echo
echo "Web dashboard:"
echo "  sudo systemctl enable --now imx-web-dashboard.service"
