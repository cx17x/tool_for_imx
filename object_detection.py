import argparse
import sys
from functools import lru_cache

import cv2

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
    def __init__(self, coords, category, conf, metadata):
        """Create a Detection object, recording the bounding box, category and confidence."""
        self.category = category
        self.conf = conf
        self.box = imx500.convert_inference_coords(coords, metadata, picam2)


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

        if not args.no_overlay and intrinsics.preserve_aspect_ratio:
            b_x, b_y, b_w, b_h = imx500.get_roi_scaled(request)
            color = (255, 0, 0)  # red
            cv2.putText(m.array, "ROI", (b_x + 5, b_y + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
            cv2.rectangle(m.array, (b_x, b_y), (b_x + b_w, b_y + b_h), (255, 0, 0, 0))

        if mjpeg_streamer is not None:
            mjpeg_streamer.publish(m.array)


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        type=str,
        help="Path of the model",
        default="/home/qwerty/q_imx_model/rpk_out/network.rpk",
    )
    parser.add_argument("--fps", type=int, help="Frames per second")
    parser.add_argument("--bbox-normalization", action=argparse.BooleanOptionalAction, help="Normalize bbox")
    parser.add_argument("--bbox-scale", type=float, default=1.0, help="Scale raw bbox output before normalization")
    parser.add_argument(
        "--bbox-order", choices=["yx", "xy"], default="yx", help="Set bbox order yx -> (y0, x0, y1, x1) xy -> (x0, y0, x1, y1)"
    )
    parser.add_argument("--threshold", type=float, default=0.55, help="Detection threshold")
    parser.add_argument(
        "--bbox-smoothing-alpha",
        type=float,
        default=0.35,
        help="EMA smoothing factor for bbox coordinates. 0 disables smoothing, higher values react faster.",
    )
    parser.add_argument("--iou", type=float, default=0.65, help="Set iou threshold")
    parser.add_argument("--max-detections", type=int, default=10, help="Set max detections")
    parser.add_argument("--ignore-dash-labels", action=argparse.BooleanOptionalAction, help="Remove '-' labels ")
    parser.add_argument("--postprocess", choices=["", "nanodet"], default=None, help="Run post process of type")
    parser.add_argument(
        "-r",
        "--preserve-aspect-ratio",
        action=argparse.BooleanOptionalAction,
        help="preserve the pixel aspect ratio of the input tensor",
    )
    parser.add_argument("--labels", type=str, default="/home/qwerty/q_imx_model/labels.txt", help="Path to the labels file")
    parser.add_argument(
        "--target-class",
        type=str,
        default="person",
        help="Only show detections for this class label. Use 'all' to show every class.",
    )
    parser.add_argument("--print-detections", action="store_true", help="Print matching detections to stdout")
    parser.add_argument("--no-udp", action="store_true", help="Disable bbox UDP publishing")
    parser.add_argument("--udp-host", type=str, default="127.0.0.1", help="BBox UDP destination host")
    parser.add_argument("--udp-port", type=int, default=5005, help="BBox UDP destination port")
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
    parser.add_argument("--no-preview", action="store_true", help="Disable local camera preview window")
    parser.add_argument("--no-overlay", action="store_true", help="Disable drawing bbox overlay on the output frame")
    parser.add_argument("--mjpeg", action="store_true", help="Serve MJPEG stream from the camera process")
    parser.add_argument("--mjpeg-host", type=str, default="0.0.0.0", help="MJPEG HTTP host")
    parser.add_argument("--mjpeg-port", type=int, default=8081, help="MJPEG HTTP port")
    parser.add_argument("--mjpeg-quality", type=int, default=75, help="MJPEG JPEG quality")
    parser.add_argument("--print-intrinsics", action="store_true", help="Print JSON network_intrinsics then exit")
    return parser.parse_args()


if __name__ == "__main__":
    args = get_args()
    if not 0.0 <= args.bbox_smoothing_alpha <= 1.0:
        print("--bbox-smoothing-alpha must be between 0 and 1", file=sys.stderr)
        exit(2)

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
    if args.video_udp:
        config = picam2.create_preview_configuration(
            main={"size": (640, 480), "format": "XBGR8888"},
            lores={"size": (480, 360), "format": "YUV420"},
            controls={"FrameRate": intrinsics.inference_rate},
            buffer_count=12,
            display="main",
            encode=args.video_stream,
        )
    else:
        config = picam2.create_preview_configuration(controls={"FrameRate": intrinsics.inference_rate}, buffer_count=12)

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
                udp_publisher.send(last_results, args.target_class, get_label_for_category)
    except KeyboardInterrupt:
        pass
    finally:
        if video_streamer is not None:
            video_streamer.stop(picam2)
        if mjpeg_streamer is not None:
            mjpeg_streamer.stop()
        if udp_publisher is not None:
            udp_publisher.close()
