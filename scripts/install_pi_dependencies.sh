#!/usr/bin/env bash
set -euo pipefail

sudo apt update
sudo apt install -y \
  python3-opencv \
  python3-picamera2 \
  python3-venv \
  ffmpeg \
  rsync

VENV_DIR="${VENV_DIR:-/home/${USER}/venv}"

if [[ ! -d "$VENV_DIR" ]]; then
  python3 -m venv --system-site-packages "$VENV_DIR"
else
  sed -i 's/^include-system-site-packages = .*/include-system-site-packages = true/' "$VENV_DIR/pyvenv.cfg"
fi

"$VENV_DIR/bin/python" - <<'PY'
import cv2
import picamera2

print("cv2:", cv2.__version__)
print("picamera2: import ok")
PY
