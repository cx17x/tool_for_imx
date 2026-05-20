import argparse
import json
import sys
from functools import lru_cache

import cv2
import numpy as np

from detection_config import DEFAULT_DETECTION_CONFIG, load_detection_config, validate_detection_config
from detection_udp import DetectionUdpPublisher
from mjpeg_streamer import MjpegStreamer
from picamera2 import MappedArray, Picamera2
from picamera2.devices import IMX500
from picamera2.devices.imx500 import NetworkIntrinsics, postprocess_nanodet_detection
from video_udp_streamer import VideoUdpStreamer

last_detections = []
detections_updated = False
mjpeg_streamer = None
smoothed_boxes = {}
bbox_tracker = None


def get_label_for_category(category):
    labels = get_labels()
    category_index = int(category)
    if 0 <= category_index < len(labels):
        return labels[category_index]
    return str(category_index)


def matches_target_class(category):
    target_class = args.target_class
    if not target_class or target_class.lower() == "all":
        return True

    return get_label_for_category(category).lower() == target_class.lower()


class Detection:
    def __init__(
        self,
        coords,
        category,
        conf,
        metadata=None,
        box=None,
        track_id=None,
        predicted=False,
        motion_vector=None,
    ):
        """Create a Detection object, recording the bounding box, category and confidence."""
        self.category = category
        self.conf = conf
        self.track_id = track_id
        self.predicted = predicted
        self.motion_vector = motion_vector
        if box is None:
            self.box = imx500.convert_inference_coords(coords, metadata, picam2)
        else:
            self.box = box


def box_to_center(box):
    x, y, w, h = box
    return np.array([x + w / 2.0, y + h / 2.0, w, h], dtype=np.float32)


def center_to_box(center):
    cx, cy, w, h = center
    w = max(float(w), 1.0)
    h = max(float(h), 1.0)
    return (cx - w / 2.0, cy - h / 2.0, w, h)


def sanitize_box(box):
    x, y, w, h = box
    w = max(float(w), 1.0)
    h = max(float(h), 1.0)
    return (int(round(x)), int(round(y)), int(round(w)), int(round(h)))


def bbox_iou(box_a, box_b):
    ax, ay, aw, ah = box_a
    bx, by, bw, bh = box_b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh

    inter_x1 = max(ax, bx)
    inter_y1 = max(ay, by)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    intersection = inter_w * inter_h
    union = aw * ah + bw * bh - intersection
    if union <= 0:
        return 0.0
    return intersection / union


class BboxKalmanFilter:
    def __init__(self, box, process_noise, measurement_noise):
        self.state = np.zeros((8, 1), dtype=np.float32)
        self.state[:4, 0] = box_to_center(box)

        self.transition = np.eye(8, dtype=np.float32)
        for i in range(4):
            self.transition[i, i + 4] = 1.0

        self.measurement = np.zeros((4, 8), dtype=np.float32)
        self.measurement[:4, :4] = np.eye(4, dtype=np.float32)

        self.covariance = np.eye(8, dtype=np.float32) * 20.0
        self.process_noise = np.eye(8, dtype=np.float32) * process_noise
        self.measurement_noise = np.eye(4, dtype=np.float32) * measurement_noise

    def predict(self):
        self.state = self.transition @ self.state
        self.covariance = self.transition @ self.covariance @ self.transition.T + self.process_noise
        return sanitize_box(center_to_box(self.state[:4, 0]))

    def update(self, box):
        measurement = box_to_center(box).reshape(4, 1)
        innovation = measurement - self.measurement @ self.state
        innovation_covariance = (
            self.measurement @ self.covariance @ self.measurement.T + self.measurement_noise
        )
        gain = self.covariance @ self.measurement.T @ np.linalg.inv(innovation_covariance)
        self.state = self.state + gain @ innovation
        identity = np.eye(8, dtype=np.float32)
        self.covariance = (identity - gain @ self.measurement) @ self.covariance
        return sanitize_box(center_to_box(self.state[:4, 0]))

    def velocity(self):
        vx, vy = self.state[4:6, 0]
        return float(vx), float(vy)


class BboxTrack:
    def __init__(self, track_id, detection, process_noise, measurement_noise):
        self.id = track_id
        self.category = detection.category
        self.conf = float(detection.conf)
        self.missed = 0
        self.age = 0
        self.predicted_box = detection.box
        self.box_filter = BboxKalmanFilter(detection.box, process_noise, measurement_noise)

    def predict(self):
        self.age += 1
        self.predicted_box = self.box_filter.predict()
        return self.predicted_box

    def update(self, detection):
        self.missed = 0
        self.category = detection.category
        self.conf = float(detection.conf)
        self.predicted_box = self.box_filter.update(detection.box)

    def mark_missed(self, confidence_decay):
        self.missed += 1
        self.conf *= confidence_decay

    def to_detection(self):
        return Detection(
            coords=None,
            category=self.category,
            conf=self.conf,
            box=self.predicted_box,
            track_id=self.id,
            predicted=self.missed > 0,
            motion_vector=self.box_filter.velocity(),
        )


class BboxTracker:
    def __init__(self, iou_threshold, max_missed, process_noise, measurement_noise, confidence_decay):
        self.iou_threshold = iou_threshold
        self.max_missed = max_missed
        self.process_noise = process_noise
        self.measurement_noise = measurement_noise
        self.confidence_decay = confidence_decay
        self.next_track_id = 1
        self.tracks = []

    def update(self, detections):
        original_track_count = len(self.tracks)
        for track in self.tracks:
            track.predict()

        matches = []
        used_tracks = set()
        used_detections = set()
        candidates = []

        for track_index, track in enumerate(self.tracks):
            for detection_index, detection in enumerate(detections):
                if int(track.category) != int(detection.category):
                    continue
                iou = bbox_iou(track.predicted_box, detection.box)
                if iou >= self.iou_threshold:
                    candidates.append((iou, track_index, detection_index))

        for _, track_index, detection_index in sorted(candidates, reverse=True):
            if track_index in used_tracks or detection_index in used_detections:
                continue
            matches.append((track_index, detection_index))
            used_tracks.add(track_index)
            used_detections.add(detection_index)

        for track_index, detection_index in matches:
            self.tracks[track_index].update(detections[detection_index])

        for detection_index, detection in enumerate(detections):
            if detection_index in used_detections:
                continue
            self.tracks.append(self._new_track(detection))

        active_tracks = []
        for track_index, track in enumerate(self.tracks):
            if track_index < original_track_count and track_index not in used_tracks:
                track.mark_missed(self.confidence_decay)
            if track.missed <= self.max_missed:
                active_tracks.append(track)

        self.tracks = active_tracks
        return [track.to_detection() for track in self.tracks]

    def _new_track(self, detection):
        track = BboxTrack(
            self.next_track_id,
            detection,
            self.process_noise,
            self.measurement_noise,
        )
        self.next_track_id += 1
        return track


def track_detections(detections):
    if bbox_tracker is None:
        return detections
    return bbox_tracker.update(detections)


def get_main_stream_size():
    config = picam2.camera_configuration()
    width, height = config["main"]["size"]
    return width, height


def smooth_detections(detections):
    """Apply lightweight EMA smoothing to bbox coordinates."""
    global smoothed_boxes
    if args.bbox_smoothing_alpha <= 0:
        smoothed_boxes = {}
        return detections

    alpha = args.bbox_smoothing_alpha
    category_counts = {}
    next_smoothed_boxes = {}

    for detection in detections:
        category = int(detection.category)
        index = category_counts.get(category, 0)
        category_counts[category] = index + 1
        key = (category, index)

        current_box = tuple(float(value) for value in detection.box)
        previous_box = smoothed_boxes.get(key)
        if previous_box is None:
            smoothed_box = current_box
        else:
            smoothed_box = tuple(
                alpha * current + (1.0 - alpha) * previous
                for current, previous in zip(current_box, previous_box)
            )

        next_smoothed_boxes[key] = smoothed_box
        detection.box = tuple(int(round(value)) for value in smoothed_box)

    smoothed_boxes = next_smoothed_boxes
    return detections


def parse_detections(metadata: dict):
    """Parse the output tensor into a number of detected objects, scaled to the ISP output."""
    global detections_updated, last_detections
    bbox_normalization = intrinsics.bbox_normalization
    bbox_order = intrinsics.bbox_order
    threshold = args.threshold
    iou = args.iou
    max_detections = args.max_detections

    np_outputs = imx500.get_outputs(metadata, add_batch=True)
    input_w, input_h = imx500.get_input_size()
    if np_outputs is None:
        detections_updated = False
        return last_detections
    detections_updated = True
    if intrinsics.postprocess == "nanodet":
        boxes, scores, classes = postprocess_nanodet_detection(
            outputs=np_outputs[0], conf=threshold, iou_thres=iou, max_out_dets=max_detections
        )[0]
        from picamera2.devices.imx500.postprocess import scale_boxes

        boxes = scale_boxes(boxes, 1, 1, input_h, input_w, False, False)
    else:
        boxes, scores, classes = np_outputs[0][0], np_outputs[1][0], np_outputs[2][0]
        if args.bbox_scale != 1.0:
            boxes = boxes * args.bbox_scale

        if bbox_normalization:
            boxes = boxes / input_h

        if bbox_order == "xy":
            boxes = boxes[:, [1, 0, 3, 2]]

    last_detections = []
    for box, score, category in zip(boxes, scores, classes):
        if score <= threshold or not matches_target_class(category):
            continue

        detection = Detection(box, category, score, metadata)
        last_detections.append(detection)

        if args.print_detections:
            label = get_label_for_category(category)
            x, y, w, h = detection.box
            print(f"{label}: conf={score:.2f}, box=({x}, {y}, {w}, {h})")

    if args.tracker:
        last_detections = track_detections(last_detections)
    else:
        last_detections = smooth_detections(last_detections)
    return last_detections


@lru_cache
def get_labels():
    labels = intrinsics.labels

    if intrinsics.ignore_dash_labels:
        labels = [label for label in labels if label and label != "-"]
    return labels


def draw_detections(request, stream="main"):
    """Draw the detections for this request onto the ISP output."""
    detections = last_results
    with MappedArray(request, stream) as m:
        if detections is not None and not args.no_overlay:
            for detection in detections:
                x, y, w, h = detection.box
                label = f"{get_label_for_category(detection.category)} ({detection.conf:.2f})"
                if detection.track_id is not None:
                    label = f"#{detection.track_id} {label}"
                if detection.predicted:
                    label = f"{label} pred"

                # Calculate text size and position
                (text_width, text_height), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                text_x = x + 5
                text_y = y + 15

                # Create a copy of the array to draw the background with opacity
                overlay = m.array.copy()

                # Draw the background rectangle on the overlay
                cv2.rectangle(
                    overlay,
                    (text_x, text_y - text_height),
                    (text_x + text_width, text_y + baseline),
                    (255, 255, 255),  # Background color (white)
                    cv2.FILLED,
                )

                alpha = 0.30
                cv2.addWeighted(overlay, alpha, m.array, 1 - alpha, 0, m.array)

                # Draw text on top of the background
                cv2.putText(m.array, label, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

                # Draw detection box
                cv2.rectangle(m.array, (x, y), (x + w, y + h), (0, 255, 0, 0), thickness=2)

                if args.motion_vector and detection.motion_vector is not None:
                    vx, vy = detection.motion_vector
                    speed = float(np.hypot(vx, vy))
                    if speed >= args.motion_vector_min_speed:
                        center_x = int(round(x + w / 2))
                        center_y = int(round(y + h / 2))
                        end_x = int(round(center_x + vx * args.motion_vector_scale))
                        end_y = int(round(center_y + vy * args.motion_vector_scale))
                        cv2.arrowedLine(
                            m.array,
                            (center_x, center_y),
                            (end_x, end_y),
                            (255, 255, 0, 0),
                            thickness=2,
                            tipLength=0.25,
                        )

        if not args.no_overlay and intrinsics.preserve_aspect_ratio:
            b_x, b_y, b_w, b_h = imx500.get_roi_scaled(request)
            color = (255, 0, 0)  # red
            cv2.putText(m.array, "ROI", (b_x + 5, b_y + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
            cv2.rectangle(m.array, (b_x, b_y), (b_x + b_w, b_y + b_h), (255, 0, 0, 0))

        if mjpeg_streamer is not None:
            mjpeg_streamer.publish(m.array)


def build_arg_parser(defaults):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, help="Path to JSON detection config")
    parser.add_argument(
        "--model",
        type=str,
        help="Path of the model",
        default=defaults["model"],
    )
    parser.add_argument("--fps", type=int, help="Frames per second")
    parser.add_argument(
        "--bbox-normalization",
        action=argparse.BooleanOptionalAction,
        default=defaults["bbox_normalization"],
        help="Normalize bbox",
    )
    parser.add_argument("--bbox-scale", type=float, default=defaults["bbox_scale"], help="Scale raw bbox output before normalization")
    parser.add_argument(
        "--bbox-order",
        choices=["yx", "xy"],
        default=defaults["bbox_order"],
        help="Set bbox order yx -> (y0, x0, y1, x1) xy -> (x0, y0, x1, y1)",
    )
    parser.add_argument("--threshold", type=float, default=defaults["threshold"], help="Detection threshold")
    parser.add_argument(
        "--bbox-smoothing-alpha",
        type=float,
        default=defaults["bbox_smoothing_alpha"],
        help="EMA smoothing factor for bbox coordinates. 0 disables smoothing, higher values react faster.",
    )
    parser.add_argument(
        "--tracker",
        action=argparse.BooleanOptionalAction,
        default=defaults["tracker"],
        help="Enable IoU track assignment with Kalman bbox prediction.",
    )
    parser.add_argument("--tracker-iou-threshold", type=float, default=defaults["tracker_iou_threshold"], help="Minimum IoU for matching detections to tracks")
    parser.add_argument("--tracker-max-missed", type=int, default=defaults["tracker_max_missed"], help="Keep predicting a track for this many missed frames")
    parser.add_argument("--tracker-process-noise", type=float, default=defaults["tracker_process_noise"], help="Kalman process noise for bbox tracking")
    parser.add_argument("--tracker-measurement-noise", type=float, default=defaults["tracker_measurement_noise"], help="Kalman measurement noise for bbox tracking")
    parser.add_argument("--tracker-confidence-decay", type=float, default=defaults["tracker_confidence_decay"], help="Confidence decay per predicted-only frame")
    parser.add_argument("--motion-vector", action=argparse.BooleanOptionalAction, default=defaults["motion_vector"], help="Draw and publish bbox center motion vectors")
    parser.add_argument("--motion-vector-scale", type=float, default=defaults["motion_vector_scale"], help="Scale factor for drawing motion vectors in pixels per frame")
    parser.add_argument("--motion-vector-min-speed", type=float, default=defaults["motion_vector_min_speed"], help="Minimum pixels per frame before drawing a motion vector")
    parser.add_argument("--iou", type=float, default=defaults["iou"], help="Set iou threshold")
    parser.add_argument("--max-detections", type=int, default=defaults["max_detections"], help="Set max detections")
    parser.add_argument("--ignore-dash-labels", action=argparse.BooleanOptionalAction, help="Remove '-' labels ")
    parser.add_argument("--postprocess", choices=["", "nanodet"], default=None, help="Run post process of type")
    parser.add_argument(
        "-r",
        "--preserve-aspect-ratio",
        action=argparse.BooleanOptionalAction,
        help="preserve the pixel aspect ratio of the input tensor",
    )
    parser.add_argument("--labels", type=str, default=defaults["labels"], help="Path to the labels file")
    parser.add_argument(
        "--target-class",
        type=str,
        default=defaults["target_class"],
        help="Only show detections for this class label. Use 'all' to show every class.",
    )
    parser.add_argument("--print-detections", action="store_true", help="Print matching detections to stdout")
    parser.add_argument("--no-udp", action="store_true", default=defaults["no_udp"], help="Disable bbox UDP publishing")
    parser.add_argument("--udp", dest="no_udp", action="store_false", help="Enable bbox UDP publishing")
    parser.add_argument("--udp-host", type=str, default=defaults["udp_host"], help="BBox UDP destination host")
    parser.add_argument("--udp-port", type=int, default=defaults["udp_port"], help="BBox UDP destination port")
    parser.add_argument("--video-udp", action="store_true", help="Stream video with bbox overlay over UDP")
    parser.add_argument("--video-udp-host", type=str, default="127.0.0.1", help="Video UDP destination host")
    parser.add_argument("--video-udp-port", type=int, default=5006, help="Video UDP destination port")
    parser.add_argument("--video-bitrate", type=int, default=1_000_000, help="Video H.264 bitrate")
    parser.add_argument(
        "--video-stream",
        choices=["lores", "main"],
        default="lores",
        help="Picamera2 stream to encode for video UDP. 'lores' is safer; 'main' can include overlay.",
    )
    parser.add_argument("--no-preview", action="store_true", default=defaults["no_preview"], help="Disable local camera preview window")
    parser.add_argument("--preview", dest="no_preview", action="store_false", help="Enable local camera preview window")
    parser.add_argument("--no-overlay", action="store_true", default=defaults["no_overlay"], help="Disable drawing bbox overlay on the output frame")
    parser.add_argument("--overlay", dest="no_overlay", action="store_false", help="Enable drawing bbox overlay on the output frame")
    parser.add_argument("--mjpeg", action=argparse.BooleanOptionalAction, default=defaults["mjpeg"], help="Serve MJPEG stream from the camera process")
    parser.add_argument("--mjpeg-host", type=str, default=defaults["mjpeg_host"], help="MJPEG HTTP host")
    parser.add_argument("--mjpeg-port", type=int, default=defaults["mjpeg_port"], help="MJPEG HTTP port")
    parser.add_argument("--mjpeg-quality", type=int, default=defaults["mjpeg_quality"], help="MJPEG JPEG quality")
    parser.add_argument("--main-width", type=int, default=defaults["main_width"], help="Main output stream width")
    parser.add_argument("--main-height", type=int, default=defaults["main_height"], help="Main output stream height")
    parser.add_argument("--print-intrinsics", action="store_true", help="Print JSON network_intrinsics then exit")
    return parser


def get_args():
    config_parser = argparse.ArgumentParser(add_help=False)
    config_parser.add_argument("--config", type=str)
    config_args, _ = config_parser.parse_known_args()

    defaults = dict(DEFAULT_DETECTION_CONFIG)
    if config_args.config:
        try:
            defaults = validate_detection_config(load_detection_config(config_args.config))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"Invalid --config {config_args.config}: {exc}", file=sys.stderr)
            exit(2)

    return build_arg_parser(defaults).parse_args()


def validate_args(args):
    config_values = {
        key: getattr(args, key)
        for key in DEFAULT_DETECTION_CONFIG
    }
    try:
        validate_detection_config(config_values)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        exit(2)


if __name__ == "__main__":
    args = get_args()
    validate_args(args)
    if not 0.0 <= args.bbox_smoothing_alpha <= 1.0:
        print("--bbox-smoothing-alpha must be between 0 and 1", file=sys.stderr)
        exit(2)
    if not 0.0 <= args.tracker_iou_threshold <= 1.0:
        print("--tracker-iou-threshold must be between 0 and 1", file=sys.stderr)
        exit(2)
    if args.tracker_max_missed < 0:
        print("--tracker-max-missed must be >= 0", file=sys.stderr)
        exit(2)
    if args.tracker_process_noise <= 0 or args.tracker_measurement_noise <= 0:
        print("--tracker-process-noise and --tracker-measurement-noise must be > 0", file=sys.stderr)
        exit(2)
    if args.main_width <= 0 or args.main_height <= 0:
        print("--main-width and --main-height must be > 0", file=sys.stderr)
        exit(2)
    if not 0.0 <= args.tracker_confidence_decay <= 1.0:
        print("--tracker-confidence-decay must be between 0 and 1", file=sys.stderr)
        exit(2)
    if args.motion_vector_scale < 0:
        print("--motion-vector-scale must be >= 0", file=sys.stderr)
        exit(2)
    if args.motion_vector_min_speed < 0:
        print("--motion-vector-min-speed must be >= 0", file=sys.stderr)
        exit(2)

    if args.tracker:
        bbox_tracker = BboxTracker(
            args.tracker_iou_threshold,
            args.tracker_max_missed,
            args.tracker_process_noise,
            args.tracker_measurement_noise,
            args.tracker_confidence_decay,
        )

    # This must be called before instantiation of Picamera2
    imx500 = IMX500(args.model)
    intrinsics = imx500.network_intrinsics
    if not intrinsics:
        intrinsics = NetworkIntrinsics()
        intrinsics.task = "object detection"
    elif intrinsics.task != "object detection":
        print("Network is not an object detection task", file=sys.stderr)
        exit()

    # Override intrinsics from args
    for key, value in vars(args).items():
        if key == 'labels' and value is not None:
            with open(value, 'r') as f:
                intrinsics.labels = f.read().splitlines()
        elif hasattr(intrinsics, key) and value is not None:
            setattr(intrinsics, key, value)

    # Defaults
    if intrinsics.labels is None:
        with open(args.labels, "r") as f:
            intrinsics.labels = f.read().splitlines()
    intrinsics.update_with_defaults()

    if args.print_intrinsics:
        print(intrinsics)
        exit()

    mjpeg_streamer = None
    if args.mjpeg:
        mjpeg_streamer = MjpegStreamer(args.mjpeg_host, args.mjpeg_port, args.mjpeg_quality)
        mjpeg_streamer.start()
        print(f"Serving MJPEG on http://{args.mjpeg_host}:{args.mjpeg_port}/mjpeg")

    picam2 = Picamera2(imx500.camera_num)
    main_stream = {"size": (args.main_width, args.main_height), "format": "XBGR8888"}
    if args.video_udp:
        config = picam2.create_preview_configuration(
            main=main_stream,
            lores={"size": (480, 360), "format": "YUV420"},
            controls={"FrameRate": intrinsics.inference_rate},
            buffer_count=12,
            display="main",
            encode=args.video_stream,
        )
    else:
        config = picam2.create_preview_configuration(
            main=main_stream,
            controls={"FrameRate": intrinsics.inference_rate},
            buffer_count=12,
        )

    imx500.show_network_fw_progress_bar()
    picam2.configure(config)

    if intrinsics.preserve_aspect_ratio:
        imx500.set_auto_aspect_ratio()

    last_results = None
    picam2.pre_callback = draw_detections

    udp_publisher = None
    if not args.no_udp:
        udp_publisher = DetectionUdpPublisher(args.udp_host, args.udp_port)
        print(f"Publishing bbox UDP to {args.udp_host}:{args.udp_port}")

    video_streamer = None
    if args.video_udp:
        video_streamer = VideoUdpStreamer(args.video_udp_host, args.video_udp_port, args.video_bitrate)
        video_streamer.start(picam2, stream_name=args.video_stream)
        print(f"Streaming video UDP from {args.video_stream} to {args.video_udp_host}:{args.video_udp_port}")

    picam2.start(show_preview=not args.no_preview)

    try:
        while True:
            last_results = parse_detections(picam2.capture_metadata())
            if udp_publisher is not None and detections_updated:
                udp_publisher.send(last_results, args.target_class, get_label_for_category, get_main_stream_size())
    except KeyboardInterrupt:
        pass
    finally:
        if video_streamer is not None:
            video_streamer.stop(picam2)
        if mjpeg_streamer is not None:
            mjpeg_streamer.stop()
        if udp_publisher is not None:
            udp_publisher.close()
