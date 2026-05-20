import argparse
import hmac
import os
import json
import mimetypes
import http.client
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = ROOT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

from detection_config import CONFIG_SCHEMA, DEFAULT_DETECTION_CONFIG, load_detection_config, validate_detection_config

STATIC_DIR = ROOT_DIR / "static"
HLS_DIR = STATIC_DIR / "hls"
DEFAULT_CONFIG_PATH = PROJECT_DIR / "config" / "object_detection.json"
DEFAULT_RESTART_HELPER = PROJECT_DIR / "scripts" / "restart_object_detection_video.sh"

mimetypes.add_type("application/vnd.apple.mpegurl", ".m3u8")
mimetypes.add_type("video/mp2t", ".ts")

state_lock = threading.Lock()
latest_bbox = {
    "ts": None,
    "target_class": None,
    "detections": [],
    "source": None,
    "received_at": None,
}
latest_seq = 0
video_process = None


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0", help="HTTP dashboard host")
    parser.add_argument("--port", type=int, default=8080, help="HTTP dashboard port")
    parser.add_argument("--bbox-host", default="127.0.0.1", help="UDP host to bind for bbox JSON")
    parser.add_argument("--bbox-port", type=int, default=5005, help="UDP port to bind for bbox JSON")
    parser.add_argument("--video-host", default="127.0.0.1", help="UDP host for incoming MPEG-TS video")
    parser.add_argument("--video-port", type=int, default=5006, help="UDP port for incoming MPEG-TS video")
    parser.add_argument("--mjpeg-host", default="127.0.0.1", help="MJPEG upstream host")
    parser.add_argument("--mjpeg-port", type=int, default=8081, help="MJPEG upstream port")
    parser.add_argument("--no-video", action="store_true", help="Disable ffmpeg UDP video to HLS bridge")
    parser.add_argument("--hls-segment-time", type=float, default=0.3, help="HLS segment length in seconds")
    parser.add_argument("--hls-list-size", type=int, default=2, help="Number of HLS segments in playlist")
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH), help="Detection JSON config path")
    parser.add_argument("--restart-helper", default=str(DEFAULT_RESTART_HELPER), help="Restart helper path")
    return parser.parse_args()


def update_bbox(payload, source):
    global latest_bbox, latest_seq
    payload["source"] = source
    payload["received_at"] = time.time()

    with state_lock:
        latest_bbox = payload
        latest_seq += 1


def bbox_udp_listener(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    print(f"Listening for bbox UDP on {host}:{port}", flush=True)

    while True:
        data, address = sock.recvfrom(65535)
        try:
            payload = json.loads(data.decode("utf-8"))
        except json.JSONDecodeError as exc:
            print(f"Invalid bbox JSON from {address}: {exc}", file=sys.stderr, flush=True)
            continue

        update_bbox(payload, f"{address[0]}:{address[1]}")


def start_video_hls_bridge(args):
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        print("ffmpeg not found, video bridge disabled", file=sys.stderr, flush=True)
        return None

    HLS_DIR.mkdir(parents=True, exist_ok=True)
    for path in HLS_DIR.glob("*"):
        if path.is_file():
            path.unlink()

    playlist = HLS_DIR / "stream.m3u8"
    input_url = f"udp://{args.video_host}:{args.video_port}?overrun_nonfatal=1&fifo_size=5000000"
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-i",
        input_url,
        "-c",
        "copy",
        "-f",
        "hls",
        "-hls_time",
        str(args.hls_segment_time),
        "-hls_list_size",
        str(args.hls_list_size),
        "-hls_flags",
        "delete_segments+append_list+omit_endlist",
        str(playlist),
    ]
    print(f"Starting video bridge: {' '.join(command)}", flush=True)
    return subprocess.Popen(command)


def get_video_status():
    playlist = HLS_DIR / "stream.m3u8"
    segments = sorted(HLS_DIR.glob("*.ts"))
    now = time.time()
    playlist_mtime = playlist.stat().st_mtime if playlist.exists() else None
    newest_segment_mtime = max((segment.stat().st_mtime for segment in segments), default=None)
    return {
        "ffmpeg_running": video_process is not None and video_process.poll() is None,
        "ffmpeg_returncode": None if video_process is None else video_process.poll(),
        "playlist_exists": playlist.exists(),
        "playlist_age": None if playlist_mtime is None else now - playlist_mtime,
        "segment_count": len(segments),
        "newest_segment_age": None if newest_segment_mtime is None else now - newest_segment_mtime,
    }


def read_current_config(path):
    config_path = Path(path)
    if not config_path.exists():
        return dict(DEFAULT_DETECTION_CONFIG)
    return validate_detection_config(load_detection_config(config_path))


def write_config_atomic(path, config):
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=config_path.parent, delete=False) as tmp_file:
        json.dump(config, tmp_file, indent=2)
        tmp_file.write("\n")
        tmp_name = tmp_file.name
    Path(tmp_name).replace(config_path)


def get_recent_service_status(service_name="imx-object-detection-video.service"):
    command = ["systemctl", "is-active", service_name]
    active = subprocess.run(command, capture_output=True, text=True, timeout=10)
    journal = subprocess.run(
        ["journalctl", "-u", service_name, "-n", "40", "--no-pager", "-o", "cat"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return {
        "active_returncode": active.returncode,
        "active": active.stdout.strip(),
        "active_stderr": active.stderr.strip(),
        "journal_returncode": journal.returncode,
        "journal": journal.stdout,
        "journal_stderr": journal.stderr,
    }


def restart_detection_service(helper_path):
    command = ["sudo", "-n", str(helper_path)]
    started_at = time.time()
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    return {
        "command": command,
        "returncode": completed.returncode,
        "duration": time.time() - started_at,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, format, *args):
        print(f"{self.address_string()} - {format % args}", flush=True)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/bbox":
            self.send_bbox_json()
            return
        if path == "/api/config":
            self.send_config_json()
            return
        if path == "/api/video-status":
            self.send_json(get_video_status())
            return
        if path == "/mjpeg":
            self.proxy_mjpeg()
            return
        if path == "/events":
            self.send_events()
            return
        if path == "/health":
            self.send_json({"ok": True, "ts": time.time()})
            return
        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/config/validate":
            self.handle_config_validate()
            return
        if path == "/api/config/apply":
            self.handle_config_apply()
            return
        self.send_error(404, "Not found")

    def require_admin_token(self):
        expected = self.server.admin_token
        if not expected:
            self.send_json({"ok": False, "error": "IMX_DASHBOARD_ADMIN_TOKEN is not configured"}, status=403)
            return False
        actual = self.headers.get("X-Admin-Token", "")
        if not hmac.compare_digest(actual, expected):
            self.send_json({"ok": False, "error": "invalid admin token"}, status=403)
            return False
        return True

    def read_json_body(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            raise ValueError("request body is empty")
        if content_length > 128 * 1024:
            raise ValueError("request body is too large")
        return json.loads(self.rfile.read(content_length).decode("utf-8"))

    def normalize_config_request(self):
        body = self.read_json_body()
        raw_config = body.get("config", body) if isinstance(body, dict) else body
        return validate_detection_config(raw_config)

    def send_config_json(self):
        try:
            config = read_current_config(self.server.config_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        self.send_json(
            {
                "ok": True,
                "config": config,
                "defaults": DEFAULT_DETECTION_CONFIG,
                "schema": CONFIG_SCHEMA,
                "config_path": str(self.server.config_path),
                "token_required": bool(self.server.admin_token),
            }
        )

    def handle_config_validate(self):
        if not self.require_admin_token():
            return
        try:
            config = self.normalize_config_request()
        except (json.JSONDecodeError, ValueError) as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400)
            return
        self.send_json({"ok": True, "config": config})

    def handle_config_apply(self):
        if not self.require_admin_token():
            return
        try:
            config = self.normalize_config_request()
            write_config_atomic(self.server.config_path, config)
            restart = restart_detection_service(self.server.restart_helper)
            status = get_recent_service_status()
        except (json.JSONDecodeError, OSError, subprocess.SubprocessError, ValueError) as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        self.send_json(
            {
                "ok": restart["returncode"] == 0,
                "config": config,
                "restart": restart,
                "status": status,
            },
            status=200 if restart["returncode"] == 0 else 500,
        )

    def proxy_mjpeg(self):
        try:
            connection = http.client.HTTPConnection(self.server.mjpeg_host, self.server.mjpeg_port, timeout=5)
            connection.request("GET", "/mjpeg")
            response = connection.getresponse()
        except OSError as exc:
            self.send_error(502, f"MJPEG upstream unavailable: {exc}")
            return

        if response.status != 200:
            self.send_error(502, f"MJPEG upstream returned {response.status}")
            connection.close()
            return

        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", response.getheader("Content-Type", "multipart/x-mixed-replace; boundary=FRAME"))
        self.end_headers()

        try:
            while True:
                chunk = response.read(65536)
                if not chunk:
                    return
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            return
        finally:
            connection.close()

    def send_bbox_json(self):
        with state_lock:
            payload = dict(latest_bbox)
            payload["seq"] = latest_seq
        self.send_json(payload)

    def send_json(self, payload, status=200):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        last_sent_seq = -1
        try:
            while True:
                with state_lock:
                    payload = dict(latest_bbox)
                    payload["seq"] = latest_seq
                    seq = latest_seq

                if seq != last_sent_seq:
                    data = json.dumps(payload, separators=(",", ":"))
                    self.wfile.write(f"event: bbox\ndata: {data}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    last_sent_seq = seq
                time.sleep(0.1)
        except (BrokenPipeError, ConnectionResetError):
            return


def main():
    global video_process
    args = get_args()
    bbox_thread = threading.Thread(
        target=bbox_udp_listener,
        args=(args.bbox_host, args.bbox_port),
        daemon=True,
    )
    bbox_thread.start()

    if not args.no_video:
        video_process = start_video_hls_bridge(args)

    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    server.mjpeg_host = args.mjpeg_host
    server.mjpeg_port = args.mjpeg_port
    server.config_path = Path(args.config_path)
    server.restart_helper = Path(args.restart_helper)
    server.admin_token = os.environ.get("IMX_DASHBOARD_ADMIN_TOKEN", "")
    print(f"Dashboard: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if video_process is not None:
            video_process.terminate()
            try:
                video_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                video_process.kill()


if __name__ == "__main__":
    main()
