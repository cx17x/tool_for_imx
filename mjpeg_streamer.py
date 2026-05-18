import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2


class MjpegStreamer:
    def __init__(self, host="0.0.0.0", port=8081, quality=75):
        self.host = host
        self.port = port
        self.quality = quality
        self.latest_jpeg = None
        self.condition = threading.Condition()
        self.server = None
        self.thread = None

    def start(self):
        streamer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_HEAD(self):
                if self.path == "/mjpeg":
                    self.send_response(200)
                    self.send_header("Age", "0")
                    self.send_header("Cache-Control", "no-cache, private")
                    self.send_header("Pragma", "no-cache")
                    self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
                    self.end_headers()
                    return

                if self.path == "/health":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    return

                self.send_response(404)
                self.end_headers()

            def do_GET(self):
                if self.path == "/health":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"ok\n")
                    return

                if self.path != "/mjpeg":
                    self.send_response(404)
                    self.end_headers()
                    return

                self.send_response(200)
                self.send_header("Age", "0")
                self.send_header("Cache-Control", "no-cache, private")
                self.send_header("Pragma", "no-cache")
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
                self.end_headers()

                while True:
                    with streamer.condition:
                        streamer.condition.wait()
                        frame = streamer.latest_jpeg

                    if frame is None:
                        continue

                    try:
                        self.wfile.write(b"--FRAME\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                        self.wfile.write(frame)
                        self.wfile.write(b"\r\n")
                    except (BrokenPipeError, ConnectionResetError):
                        return

        self.server = ThreadingHTTPServer((self.host, self.port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

    def publish(self, frame):
        if frame is None:
            return

        image = frame
        if len(image.shape) == 3 and image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)

        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
        if not ok:
            return

        with self.condition:
            self.latest_jpeg = encoded.tobytes()
            self.condition.notify_all()
