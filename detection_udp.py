import json
import socket
import time


class DetectionUdpPublisher:
    def __init__(self, host="127.0.0.1", port=5005):
        self.address = (host, port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def close(self):
        self.socket.close()

    def send(self, detections, target_class, label_resolver):
        payload = {
            "ts": time.time(),
            "target_class": target_class,
            "detections": [
                self._serialize_detection(detection, label_resolver)
                for detection in detections
            ],
        }
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.socket.sendto(data, self.address)

    @staticmethod
    def _serialize_detection(detection, label_resolver):
        x, y, w, h = detection.box
        return {
            "label": label_resolver(detection.category),
            "conf": float(detection.conf),
            "bbox": {
                "x": int(x),
                "y": int(y),
                "w": int(w),
                "h": int(h),
            },
            "center": {
                "x": int(x + w / 2),
                "y": int(y + h / 2),
            },
        }
