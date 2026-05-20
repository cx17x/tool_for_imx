import json
from pathlib import Path


DEFAULT_DETECTION_CONFIG = {
    "model": "/home/qwerty/q_imx_model/rpk_out/network.rpk",
    "labels": "/home/qwerty/q_imx_model/labels.txt",
    "target_class": "airplane",
    "threshold": 0.10,
    "iou": 0.45,
    "max_detections": 10,
    "bbox_normalization": True,
    "bbox_order": "xy",
    "bbox_scale": 1.0,
    "bbox_smoothing_alpha": 0.35,
    "tracker": True,
    "tracker_iou_threshold": 0.2,
    "tracker_max_missed": 2,
    "tracker_process_noise": 4.0,
    "tracker_measurement_noise": 30.0,
    "tracker_confidence_decay": 0.85,
    "motion_vector": True,
    "motion_vector_scale": 5.0,
    "motion_vector_min_speed": 0.2,
    "main_width": 640,
    "main_height": 640,
    "mjpeg": True,
    "mjpeg_host": "0.0.0.0",
    "mjpeg_port": 8081,
    "mjpeg_quality": 90,
    "no_preview": True,
    "no_overlay": False,
    "no_udp": False,
    "udp_host": "127.0.0.1",
    "udp_port": 5005,
}


CONFIG_SCHEMA = {
    "model": {"type": "string", "label": "Model path", "section": "model", "required": True},
    "labels": {"type": "string", "label": "Labels path", "section": "model", "required": True},
    "target_class": {"type": "string", "label": "Target class", "section": "detection"},
    "threshold": {"type": "number", "label": "Threshold", "section": "detection", "min": 0.0, "max": 1.0, "step": 0.01},
    "iou": {"type": "number", "label": "NMS IoU", "section": "detection", "min": 0.0, "max": 1.0, "step": 0.01},
    "max_detections": {"type": "integer", "label": "Max detections", "section": "detection", "min": 1, "max": 100},
    "bbox_normalization": {"type": "boolean", "label": "BBox normalization", "section": "detection"},
    "bbox_order": {"type": "select", "label": "BBox order", "section": "detection", "options": ["xy", "yx"]},
    "bbox_scale": {"type": "number", "label": "BBox scale", "section": "detection", "min": 0.0, "step": 0.01},
    "bbox_smoothing_alpha": {"type": "number", "label": "Smoothing alpha", "section": "detection", "min": 0.0, "max": 1.0, "step": 0.01},
    "tracker": {"type": "boolean", "label": "Enable tracker", "section": "tracker"},
    "tracker_iou_threshold": {"type": "number", "label": "Tracker IoU", "section": "tracker", "min": 0.0, "max": 1.0, "step": 0.01},
    "tracker_max_missed": {"type": "integer", "label": "Max missed frames", "section": "tracker", "min": 0, "max": 120},
    "tracker_process_noise": {"type": "number", "label": "Process noise", "section": "tracker", "min": 0.0001, "step": 0.1},
    "tracker_measurement_noise": {"type": "number", "label": "Measurement noise", "section": "tracker", "min": 0.0001, "step": 0.1},
    "tracker_confidence_decay": {"type": "number", "label": "Confidence decay", "section": "tracker", "min": 0.0, "max": 1.0, "step": 0.01},
    "motion_vector": {"type": "boolean", "label": "Enable motion vector", "section": "motion"},
    "motion_vector_scale": {"type": "number", "label": "Vector scale", "section": "motion", "min": 0.0, "step": 0.1},
    "motion_vector_min_speed": {"type": "number", "label": "Min vector speed", "section": "motion", "min": 0.0, "step": 0.1},
    "main_width": {"type": "integer", "label": "Main width", "section": "video", "min": 1, "max": 4096},
    "main_height": {"type": "integer", "label": "Main height", "section": "video", "min": 1, "max": 4096},
    "mjpeg": {"type": "boolean", "label": "Enable MJPEG", "section": "video"},
    "mjpeg_host": {"type": "string", "label": "MJPEG host", "section": "video", "required": True},
    "mjpeg_port": {"type": "integer", "label": "MJPEG port", "section": "video", "min": 1, "max": 65535},
    "mjpeg_quality": {"type": "integer", "label": "MJPEG quality", "section": "video", "min": 1, "max": 100},
    "no_preview": {"type": "boolean", "label": "Disable local preview", "section": "video"},
    "no_overlay": {"type": "boolean", "label": "Disable overlay", "section": "video"},
    "no_udp": {"type": "boolean", "label": "Disable bbox UDP", "section": "video"},
    "udp_host": {"type": "string", "label": "BBox UDP host", "section": "video", "required": True},
    "udp_port": {"type": "integer", "label": "BBox UDP port", "section": "video", "min": 1, "max": 65535},
}


def load_detection_config(path):
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as config_file:
        return json.load(config_file)


def validate_detection_config(config):
    if not isinstance(config, dict):
        raise ValueError("config must be a JSON object")

    normalized = dict(DEFAULT_DETECTION_CONFIG)
    unknown_keys = sorted(set(config) - set(CONFIG_SCHEMA))
    if unknown_keys:
        raise ValueError(f"unknown config keys: {', '.join(unknown_keys)}")

    for key, value in config.items():
        schema = CONFIG_SCHEMA[key]
        normalized[key] = _coerce_value(key, value, schema)

    return normalized


def _coerce_value(key, value, schema):
    value_type = schema["type"]
    if value_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be boolean")
        return value

    if value_type == "string":
        if not isinstance(value, str):
            raise ValueError(f"{key} must be string")
        if schema.get("required") and not value.strip():
            raise ValueError(f"{key} must not be empty")
        return value.strip()

    if value_type == "select":
        if value not in schema["options"]:
            raise ValueError(f"{key} must be one of: {', '.join(schema['options'])}")
        return value

    if value_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{key} must be integer")
        return _check_range(key, value, schema)

    if value_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be number")
        return float(_check_range(key, value, schema))

    raise ValueError(f"unsupported schema type for {key}")


def _check_range(key, value, schema):
    if "min" in schema and value < schema["min"]:
        raise ValueError(f"{key} must be >= {schema['min']}")
    if "max" in schema and value > schema["max"]:
        raise ValueError(f"{key} must be <= {schema['max']}")
    return value
