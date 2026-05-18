#!/usr/bin/env bash
set -euo pipefail

echo "== host =="
hostname
date
pwd

echo
echo "== python imports =="
/home/qwerty/venv/bin/python - <<'PY' || true
import sys
print("python:", sys.executable)
for module in ("cv2", "picamera2"):
    try:
        imported = __import__(module)
        print(f"{module}: ok", getattr(imported, "__version__", ""))
    except Exception as exc:
        print(f"{module}: FAIL {exc}")
PY

echo
echo "== model files =="
ls -lh /home/qwerty/q_imx_model/rpk_out/network.rpk /home/qwerty/q_imx_model/labels.txt || true

echo
echo "== services =="
systemctl is-active imx-object-detection.service imx-object-detection-video.service imx-web-dashboard.service imx-bbox-receiver.service || true
systemctl status imx-object-detection-video.service --no-pager -l || true
systemctl status imx-web-dashboard.service --no-pager -l || true

echo
echo "== unit ExecStart =="
systemctl cat imx-object-detection-video.service || true
systemctl cat imx-web-dashboard.service || true

echo
echo "== processes =="
ps aux | grep -E 'object_detection|web_dashboard|ffmpeg' | grep -v grep || true

echo
echo "== udp/tcp ports =="
ss -lunpt | grep -E '(:5005|:5006|:8080)' || true

echo
echo "== dashboard health =="
curl -s http://127.0.0.1:8080/health || true
echo
curl -s http://127.0.0.1:8080/api/video-status || true
echo

echo
echo "== hls files =="
ls -lh /home/qwerty/tool_for_imx/web_dashboard/static/hls || true

echo
echo "== recent object detection video logs =="
journalctl -u imx-object-detection-video.service -n 120 --no-pager -o cat || true

echo
echo "== recent dashboard logs =="
journalctl -u imx-web-dashboard.service -n 120 --no-pager -o cat || true
