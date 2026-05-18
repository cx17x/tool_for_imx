import argparse
import os
from pathlib import Path

import cv2
import Imath
import numpy as np
import OpenEXR


def resize_for_tensor(frame, width, height, mode):
    if mode == "stretch":
        return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)

    src_h, src_w = frame.shape[:2]
    scale = max(width / src_w, height / src_h)
    resized_w = int(round(src_w * scale))
    resized_h = int(round(src_h * scale))

    resized = cv2.resize(frame, (resized_w, resized_h), interpolation=cv2.INTER_AREA)
    left = (resized_w - width) // 2
    top = (resized_h - height) // 2
    return resized[top : top + height, left : left + width]


def write_rgb_float_exr(path, bgr_image):
    rgb = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0

    header = OpenEXR.Header(rgb.shape[1], rgb.shape[0])
    float_channel = Imath.Channel(Imath.PixelType(Imath.PixelType.FLOAT))
    header["channels"] = {"R": float_channel, "G": float_channel, "B": float_channel}

    r = np.ascontiguousarray(rgb[:, :, 0]).tobytes()
    g = np.ascontiguousarray(rgb[:, :, 1]).tobytes()
    b = np.ascontiguousarray(rgb[:, :, 2]).tobytes()

    exr = OpenEXR.OutputFile(str(path), header)
    try:
        exr.writePixels({"R": r, "G": g, "B": b})
    finally:
        exr.close()


def convert_video(args):
    video_path = Path(args.video)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    source_fps = cap.get(cv2.CAP_PROP_FPS) or 0
    frame_step = args.step
    if args.fps and source_fps > 0:
        frame_step = max(1, round(source_fps / args.fps))

    saved = 0
    frame_index = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        if frame_index % frame_step == 0:
            tensor_image = resize_for_tensor(frame, args.width, args.height, args.resize_mode)
            output_path = output_dir / f"frame_{saved:05d}.exr"
            write_rgb_float_exr(output_path, tensor_image)
            saved += 1

            if args.max_frames and saved >= args.max_frames:
                break

        frame_index += 1

    cap.release()
    print(f"Saved {saved} EXR tensors to {output_dir}")


def get_args():
    parser = argparse.ArgumentParser(
        description="Prepare RGB float EXR input tensors for imx500_object_detection_injection_demo.py"
    )
    parser.add_argument("--video", default="IMG_8811.MOV", help="Input video path")
    parser.add_argument("--output-dir", default="tensors_IMG_8811", help="Directory for generated .exr files")
    parser.add_argument("--width", type=int, default=320, help="Model input tensor width")
    parser.add_argument("--height", type=int, default=320, help="Model input tensor height")
    parser.add_argument(
        "--resize-mode",
        choices=["crop", "stretch"],
        default="crop",
        help="crop preserves aspect ratio with center crop; stretch resizes directly",
    )
    parser.add_argument("--step", type=int, default=10, help="Save every Nth video frame")
    parser.add_argument("--fps", type=float, help="Alternative to --step: approximate output FPS")
    parser.add_argument("--max-frames", type=int, help="Stop after writing this many frames")
    return parser.parse_args()


if __name__ == "__main__":
    convert_video(get_args())
