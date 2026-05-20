import json
import socket
import time


def _clamp01(value):
    return max(0.0, min(1.0, float(value)))


class DetectionUdpPublisher:
    def __init__(self, host="127.0.0.1", port=5005):
        self.address = (host, port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def close(self):
        self.socket.close()

    def send(self, detections, target_class, label_resolver, image_size=None):
        payload = {
            "ts": time.time(),
            "target_class": target_class,
            "detections": [
                self._serialize_detection(detection, label_resolver, image_size)
                for detection in detections
            ],
        }
        if image_size is not None:
            width, height = image_size
            payload["image"] = {
                "width": int(width),
                "height": int(height),
            }
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.socket.sendto(data, self.address)

    @staticmethod
    def _serialize_detection(detection, label_resolver, image_size=None):
        x, y, w, h = detection.box
        center_x = x + w / 2
        center_y = y + h / 2
        payload = {
            "label": label_resolver(detection.category),
            "conf": float(detection.conf),
            "bbox": {
                "x": int(x),
                "y": int(y),
                "w": int(w),
                "h": int(h),
            },
            "center": {
                "x": int(center_x),
                "y": int(center_y),
            },
        }
        if image_size is not None:
            width, height = image_size
            if width > 0 and height > 0:
                payload["bbox_yolo"] = {
                    "x": _clamp01(x / width),
                    "y": _clamp01(y / height),
                    "w": _clamp01(w / width),
                    "h": _clamp01(h / height),
                }
                payload["center_yolo"] = {
                    "x": _clamp01(center_x / width),
                    "y": _clamp01(center_y / height),
                }
        if getattr(detection, "track_id", None) is not None:
            payload["track_id"] = int(detection.track_id)
        if getattr(detection, "predicted", False):
            payload["predicted"] = True
        motion_vector = getattr(detection, "motion_vector", None)
        if motion_vector is not None:
            vx, vy = motion_vector
            payload["motion_vector"] = {
                "vx": float(vx),
                "vy": float(vy),
                "speed": float((vx * vx + vy * vy) ** 0.5),
            }
        return payload
