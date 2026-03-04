#!/usr/bin/env python3
"""Triangulate LED coordinates using a simplified (no calibration) camera model.

This script reads the processed images from multiple vantages, detects the LED
center in each image, and triangulates a 3D point using a simple pinhole model.
It supports selecting a shared ROI (to avoid mirrors/reflections), choosing the
best opposite-view pair, and filtering low-brightness detections. Use it when
you do not have a camera calibration step and want a quick end-to-end scan.
"""

import argparse
from pathlib import Path

import cv2
import numpy as np

DEFAULT_VANTAGES = [0, 90, 180, 270]


def find_led_center(gray, threshold_ratio=0.8):
    """Detect the brightest LED blob in a grayscale image."""
    _, max_val, _, _ = cv2.minMaxLoc(gray)
    if max_val < 1:
        return None, max_val

    _, binary = cv2.threshold(gray, max_val * threshold_ratio, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, max_val

    largest = max(contours, key=cv2.contourArea)
    M = cv2.moments(largest)
    if M["m00"] == 0:
        return None, max_val

    cx = M["m10"] / M["m00"]
    cy = M["m01"] / M["m00"]
    return (cx, cy), max_val


def rotation_y(deg):
    """Rotation matrix around Y axis."""
    rad = np.deg2rad(deg)
    return np.array(
        [
            [np.cos(rad), 0, np.sin(rad)],
            [0, 1, 0],
            [-np.sin(rad), 0, np.cos(rad)],
        ],
        dtype=np.float32,
    )


def build_projection_matrices(angles_deg, camera_z, K):
    """
    Build simplified projection matrices without calibration.
    Uses a rough pinhole model with fixed camera distance.
    """
    matrices = []
    for angle in angles_deg:
        R = rotation_y(-angle)
        t = np.array([[0.0], [0.0], [camera_z]], dtype=np.float32)
        Rt = np.hstack([R, t])
        matrices.append(K @ Rt)
    return matrices


def select_roi(image_path, window_title):
    """
    Let the user select a ROI on the given image.
    Returns (x, y, w, h) or None if selection is canceled.
    """
    img = cv2.imread(str(image_path))
    if img is None:
        raise RuntimeError(f"Could not load image for ROI selection: {image_path}")
    roi = cv2.selectROI(window_title, img, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow(window_title)
    if roi == (0, 0, 0, 0):
        return None
    return roi


def build_roi_reference_image(image_dir, led_index, num_vantages):
    """
    Build a combined reference image from a single LED index across vantages.
    """
    images = []
    for vp in range(num_vantages):
        img_path = image_dir / f"vantage_{vp}" / f"led_{led_index}_processed.jpg"
        img = cv2.imread(str(img_path))
        if img is not None:
            images.append(img)
    if not images:
        raise RuntimeError("No sample images found for ROI selection.")

    base = images[0]
    h, w = base.shape[:2]
    acc = np.zeros((h, w, 3), dtype=np.float32)
    for img in images:
        if img.shape[:2] != (h, w):
            img = cv2.resize(img, (w, h))
        acc += img.astype(np.float32)
    max_val = acc.max()
    if max_val <= 0:
        return acc.astype(np.uint8)
    acc = (acc / max_val) * 255.0
    return np.clip(acc, 0, 255).astype(np.uint8)


def build_roi_reference_image_all(image_dir, num_vantages):
    """
    Build a combined reference image by summing all processed images.
    """
    acc = None
    h = w = None
    count = 0
    for vp in range(num_vantages):
        vp_dir = image_dir / f"vantage_{vp}"
        for img_path in sorted(vp_dir.glob("led_*_processed.jpg")):
            img = cv2.imread(str(img_path))
            if img is None:
                continue
            if acc is None:
                h, w = img.shape[:2]
                acc = np.zeros((h, w, 3), dtype=np.float32)
            if img.shape[:2] != (h, w):
                img = cv2.resize(img, (w, h))
            acc += img.astype(np.float32)
            count += 1
    if acc is None or count == 0:
        raise RuntimeError("No processed images found for ROI selection.")
    max_val = acc.max()
    if max_val <= 0:
        return acc.astype(np.uint8)
    acc = (acc / max_val) * 255.0
    return np.clip(acc, 0, 255).astype(np.uint8)


def triangulate_led(uv_coords, P_matrices):
    """Triangulate 3D coordinates using 2+ vantage points."""
    valid = [(i, c) for i, c in enumerate(uv_coords) if c is not None]
    if len(valid) < 2:
        return None

    i1, (u1, v1) = valid[0]
    i2, (u2, v2) = valid[1]

    uv1 = np.array([u1, v1, 1], dtype=np.float32).reshape(3, 1)
    uv2 = np.array([u2, v2, 1], dtype=np.float32).reshape(3, 1)

    P1 = P_matrices[i1]
    P2 = P_matrices[i2]

    A = np.vstack(
        [
            uv1[0] * P1[2] - P1[0],
            uv1[1] * P1[2] - P1[1],
            uv2[0] * P2[2] - P2[0],
            uv2[1] * P2[2] - P2[1],
        ]
    )

    _, _, Vt = np.linalg.svd(A)
    X_hom = Vt[-1]
    X_hom /= X_hom[3]
    return tuple(X_hom[:3])


def parse_args():
    """Parse CLI args for rough (no calibration) triangulation."""
    parser = argparse.ArgumentParser(description="Triangulate LEDs without calibration.")
    parser.add_argument(
        "--captures-dir", default="captures", help="Capture folder (relative to scanning/)"
    )
    parser.add_argument(
        "--output-file",
        default="led_coordinates_3d_raw.txt",
        help="Output file in scanning/data/",
    )
    parser.add_argument("--num-leds", type=int, default=400, help="Total number of LEDs to process")
    parser.add_argument(
        "--camera-z", type=float, default=200.0, help="Assumed camera distance (arbitrary units)"
    )
    parser.add_argument("--focal-length", type=float, help="Approximate focal length in pixels")
    parser.add_argument(
        "--select-roi", action="store_true", help="Select ROI per vantage to ignore reflections"
    )
    parser.add_argument(
        "--roi", type=int, nargs=4, metavar=("X", "Y", "W", "H"), help="Fixed ROI for all vantages"
    )
    parser.add_argument("--roi-sample-index", type=int, help="LED index to use for ROI selection")
    parser.add_argument(
        "--min-brightness", type=float, default=10.0, help="Reject detections below this brightness"
    )
    parser.add_argument(
        "--pair",
        choices=["best_opposite", "auto", "front_back", "left_right"],
        default="best_opposite",
        help="Choose how to select vantages for triangulation",
    )
    return parser.parse_args()


def build_intrinsics(image_shape, focal_length=None):
    """Build a rough camera intrinsic matrix using image size."""
    height, width = image_shape[:2]
    if focal_length is None:
        focal_length = max(width, height)
    cx = width / 2.0
    cy = height / 2.0
    return np.array(
        [
            [focal_length, 0.0, cx],
            [0.0, focal_length, cy],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )


def pick_best_pair(centers, brightness, mode="best_opposite"):
    """Choose vantages for triangulation based on opposite-view logic."""
    pair_0 = (0, 2)
    pair_1 = (1, 3)

    def pair_score(idx_a, idx_b):
        if centers[idx_a] is None or centers[idx_b] is None:
            return None
        return brightness[idx_a] + brightness[idx_b]

    if mode == "front_back":
        chosen = [None] * len(centers)
        if centers[pair_0[0]] is not None and centers[pair_0[1]] is not None:
            chosen[pair_0[0]] = centers[pair_0[0]]
            chosen[pair_0[1]] = centers[pair_0[1]]
        return chosen, pair_0
    if mode == "left_right":
        chosen = [None] * len(centers)
        if centers[pair_1[0]] is not None and centers[pair_1[1]] is not None:
            chosen[pair_1[0]] = centers[pair_1[0]]
            chosen[pair_1[1]] = centers[pair_1[1]]
        return chosen, pair_1
    if mode == "best_opposite":
        chosen = [None] * len(centers)
        if centers[pair_0[0]] is not None or centers[pair_0[1]] is not None:
            idx = pair_0[0] if brightness[pair_0[0]] >= brightness[pair_0[1]] else pair_0[1]
            if centers[idx] is not None:
                chosen[idx] = centers[idx]
        if centers[pair_1[0]] is not None or centers[pair_1[1]] is not None:
            idx = pair_1[0] if brightness[pair_1[0]] >= brightness[pair_1[1]] else pair_1[1]
            if centers[idx] is not None:
                chosen[idx] = centers[idx]
        return chosen, ("best_opposite",)

    score_0 = pair_score(*pair_0)
    score_1 = pair_score(*pair_1)

    chosen = [None] * len(centers)
    if score_0 is None and score_1 is None:
        return chosen, None
    if score_1 is None or (score_0 is not None and score_0 >= score_1):
        chosen[pair_0[0]] = centers[pair_0[0]]
        chosen[pair_0[1]] = centers[pair_0[1]]
        return chosen, pair_0
    chosen[pair_1[0]] = centers[pair_1[0]]
    chosen[pair_1[1]] = centers[pair_1[1]]
    return chosen, pair_1


def load_processed_gray(image_dir, led_index, vp):
    """Load a processed image and return its grayscale version."""
    img_path = image_dir / f"vantage_{vp}" / f"led_{led_index}_processed.jpg"
    if not img_path.is_file():
        print(f"[LED {led_index}, Vantage {vp}] Image missing.")
        return None
    img = cv2.imread(str(img_path))
    if img is None:
        print(f"[LED {led_index}, Vantage {vp}] Could not read image.")
        return None
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def main():
    """Process captured images and generate rough 3D coordinates."""
    args = parse_args()
    base_dir = Path(__file__).resolve().parents[1]
    image_dir = base_dir / args.captures_dir
    output_path = base_dir / "data" / args.output_file

    sample_index = args.roi_sample_index or (args.num_leds // 2)
    sample_path = image_dir / "vantage_0" / f"led_{sample_index}_processed.jpg"
    if not sample_path.exists():
        raise RuntimeError(f"Sample image not found for intrinsics: {sample_path}")
    sample_img = cv2.imread(str(sample_path))
    if sample_img is None:
        raise RuntimeError(f"Could not read sample image for intrinsics: {sample_path}")

    K = build_intrinsics(sample_img.shape, focal_length=args.focal_length)
    p_matrices = build_projection_matrices(DEFAULT_VANTAGES, args.camera_z, K)
    rois = [None] * len(DEFAULT_VANTAGES)
    if args.roi:
        rois = [tuple(args.roi)] * len(DEFAULT_VANTAGES)
    elif args.select_roi:
        if args.roi_sample_index is None:
            combined = build_roi_reference_image_all(image_dir, len(DEFAULT_VANTAGES))
            tmp_name = "_roi_sample_all.jpg"
        else:
            combined = build_roi_reference_image(
                image_dir, args.roi_sample_index, len(DEFAULT_VANTAGES)
            )
            tmp_name = f"_roi_sample_{args.roi_sample_index}.jpg"
        tmp_path = image_dir / tmp_name
        cv2.imwrite(str(tmp_path), combined)
        roi = select_roi(tmp_path, "Select ROI for all vantages")
        print(f"Selected ROI: {roi}")
        rois = [roi] * len(DEFAULT_VANTAGES)

    with open(output_path, "w") as f:
        f.write("")

    for led_idx in range(args.num_leds):
        uv_coords = [None] * len(DEFAULT_VANTAGES)
        brightness = [0.0] * len(DEFAULT_VANTAGES)
        centers = [None] * len(DEFAULT_VANTAGES)

        for vp in range(len(DEFAULT_VANTAGES)):
            gray = load_processed_gray(image_dir, led_idx, vp)
            if gray is None:
                continue
            roi = rois[vp]
            if roi:
                x, y, w, h = roi
                gray_roi = gray[y : y + h, x : x + w]
            else:
                gray_roi = gray
            center, max_val = find_led_center(gray_roi)
            if center is None or max_val < args.min_brightness:
                print(f"[LED {led_idx}, Vantage {vp}] LED not detected.")
                continue

            if roi:
                center = (center[0] + x, center[1] + y)
            centers[vp] = center
            brightness[vp] = max_val
            print(f"[LED {led_idx}, Vantage {vp}] Center = {center} Brightness = {max_val}")

        uv_coords, chosen_pair = pick_best_pair(centers, brightness, mode=args.pair)
        if chosen_pair is not None:
            print(f"[LED {led_idx}] Using pair {chosen_pair} for triangulation")

        X_3d = triangulate_led(uv_coords, p_matrices)
        if X_3d is None:
            print(f"[LED {led_idx}] => Insufficient data for triangulation.\n")
        else:
            print(f"[LED {led_idx}] => 3D Position = {X_3d}\n")
            with open(output_path, "a") as f:
                f.write(f"LED {led_idx}: ({X_3d[0]:.6f}, {X_3d[1]:.6f}, {X_3d[2]:.6f})\n")


if __name__ == "__main__":
    main()
