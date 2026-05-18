#!/usr/bin/env bash
set -euo pipefail

TIMEOUT_SECONDS="${1:-60}"
DEADLINE=$((SECONDS + TIMEOUT_SECONDS))

while (( SECONDS < DEADLINE )); do
  output="$(rpicam-hello --list-cameras 2>&1 || true)"
  if echo "$output" | grep -qi 'No cameras available'; then
    sleep 2
    continue
  fi

  if echo "$output" | grep -qiE 'Available cameras|imx|/base/'; then
    exit 0
  fi
  sleep 2
done

echo "Camera did not appear within ${TIMEOUT_SECONDS}s" >&2
rpicam-hello --list-cameras >&2 || true
exit 1
