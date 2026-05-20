#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 0 ]]; then
  echo "This helper does not accept arguments." >&2
  exit 2
fi

SERVICE_NAME="imx-object-detection-video.service"

systemctl restart "$SERVICE_NAME"
systemctl is-active "$SERVICE_NAME"
journalctl -u "$SERVICE_NAME" -n 40 --no-pager -o cat
