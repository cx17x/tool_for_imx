#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/pi/tool_for_imx}"
SERVICE_USER="${SERVICE_USER:-pi}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"

cd "$(dirname "$0")/.."

install_service() {
  local source_file="$1"
  local target_file="$SYSTEMD_DIR/$(basename "$source_file")"

  sed \
    -e "s|WorkingDirectory=/home/pi/tool_for_imx|WorkingDirectory=$PROJECT_DIR|g" \
    -e "s|/home/pi/tool_for_imx|$PROJECT_DIR|g" \
    -e "s|User=pi|User=$SERVICE_USER|g" \
    "$source_file" | sudo tee "$target_file" >/dev/null

  sudo chmod 0644 "$target_file"
  echo "Installed $target_file"
}

install_service systemd/imx-object-detection.service
install_service systemd/imx-object-detection-video.service
install_service systemd/imx-bbox-receiver.service

sudo systemctl daemon-reload

echo
echo "Installed systemd services."
echo "Enable one object-detection service, not both:"
echo "  sudo systemctl enable --now imx-object-detection.service"
echo "  sudo systemctl enable --now imx-object-detection-video.service"
echo
echo "Optional debug receiver:"
echo "  sudo systemctl enable --now imx-bbox-receiver.service"
