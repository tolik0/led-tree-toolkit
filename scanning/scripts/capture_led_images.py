"""Capture per-LED images from multiple vantages for later triangulation.

This script drives one LED at a time over WebSocket, waits for the camera to
settle, and captures a frame. For each LED and vantage it stores:
- raw color image
- processed grayscale image (blurred)
- annotated image with detected LED center

It also appends a text log with the detected center and brightness, which is
used by the triangulation step.
"""

import argparse
import time
from pathlib import Path

import cv2
import websocket

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
BASE_DIR = Path(__file__).resolve().parents[1]


def init_camera(camera_index, warmup_frames=5):
    """Open the camera and warm it up before use."""
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera index {camera_index}")
    for _ in range(warmup_frames):
        cap.read()
    return cap


def set_camera_stable_exposure(cap):
    """Best-effort camera settings for repeatable brightness."""
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)  # manual (backend-specific)
    cap.set(cv2.CAP_PROP_EXPOSURE, -6)  # tweak as needed
    cap.set(cv2.CAP_PROP_AUTO_WB, 0)


def capture_frame(cap):
    """Capture a single frame."""
    ret, frame = cap.read()
    if not ret:
        raise RuntimeError("Failed to capture image.")
    return frame


def find_led_center(gray, threshold_ratio=0.8):
    """Find the centroid of the brightest blob."""
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


def capture_and_find_center(cap, led_index, vantage_point, capture_dir, apply_blur=True):
    """Capture an image and detect the LED center, saving debug frames."""
    vantage_folder = capture_dir / f"vantage_{vantage_point}"
    vantage_folder.mkdir(parents=True, exist_ok=True)

    frame = capture_frame(cap)

    raw_filename = vantage_folder / f"led_{led_index}_raw.jpg"
    cv2.imwrite(raw_filename, frame)

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    if apply_blur:
        gray = cv2.GaussianBlur(gray, (9, 9), 2)

    processed_filename = vantage_folder / f"led_{led_index}_processed.jpg"
    cv2.imwrite(processed_filename, gray)

    center, max_val = find_led_center(gray)
    print(f"[Vantage {vantage_point} | LED {led_index}] Center={center} Max={max_val}")

    if center is not None:
        c_int = (int(center[0]), int(center[1]))
        cv2.circle(frame, c_int, 10, (0, 0, 255), 2)

    annotated_filename = vantage_folder / f"led_{led_index}_annotated.jpg"
    cv2.imwrite(annotated_filename, frame)

    return center, max_val


def send_led_request(ws, led_index, num_leds, color=(255, 255, 255)):
    """Send a binary frame to light a single LED."""
    r, g, b = color
    data = bytearray(3 * num_leds)
    offset = led_index * 3
    data[offset + 0] = r
    data[offset + 1] = g
    data[offset + 2] = b

    ws.send(data, opcode=0x2)
    print(f"Sent request to turn on LED {led_index} with color {color}")

    time.sleep(0.15)


# ------------------------------
# WebSocket event handlers
# ------------------------------
def on_message(ws, message):
    print(f"Received message: {message}")


def on_error(ws, error):
    print(f"Error: {error}")


def on_close(ws, close_status_code, close_msg):
    print("Closed connection")


def append_coordinate(path, led_index, vp, center, brightness):
    """Append a single LED detection line to the coordinate file."""
    with open(path, "a") as file:
        file.write(f"VP={vp}, LED={led_index}, Coords={center}, Brightness={brightness}\n")


def scan_leds(ws, args):
    """Main scan loop across vantages and LEDs."""
    capture_dir = BASE_DIR / args.captures_dir
    capture_dir.mkdir(parents=True, exist_ok=True)
    coord_path = DATA_DIR / args.detections_file

    cap = init_camera(args.camera_index, warmup_frames=args.warmup_frames)
    if args.lock_exposure:
        set_camera_stable_exposure(cap)

    try:
        for vp in range(args.vantage_points):
            input(f"\n--> Move the camera/tree to vantage point {vp}. Press Enter when ready...")

            for led_index in range(args.num_leds):
                send_led_request(ws, led_index, args.num_leds, color=(255, 255, 255))

                center, brightness = capture_and_find_center(
                    cap, led_index, vp, capture_dir, apply_blur=True
                )

                if center is not None:
                    append_coordinate(coord_path, led_index, vp, center, brightness)

                time.sleep(args.inter_led_delay)

            print(f"Finished scanning vantage point {vp}.\n")

        data_off = bytearray(3 * args.num_leds)
        ws.send(data_off, opcode=0x2)
        print("All LEDs turned off. Scanning completed.")
    finally:
        cap.release()


def parse_args():
    """
    Parse CLI args to make scanning easier to tweak per setup.
    """
    parser = argparse.ArgumentParser(description="Scan LEDs and capture per-vantage images.")
    parser.add_argument("--ws-url", default="ws://192.168.1.120/ws", help="ESP32 WebSocket URL")
    parser.add_argument("--num-leds", type=int, default=400, help="Total LED count")
    parser.add_argument("--vantage-points", type=int, default=4, help="Number of camera vantages")
    parser.add_argument("--camera-index", type=int, default=0, help="OpenCV camera index")
    parser.add_argument(
        "--captures-dir", default="captures", help="Capture folder (relative to scanning/)"
    )
    parser.add_argument(
        "--detections-file",
        default="led_detections_2d.txt",
        help="Output detections file in scanning/data/",
    )
    parser.add_argument(
        "--warmup-frames", type=int, default=5, help="Warmup frames before scanning"
    )
    parser.add_argument(
        "--inter-led-delay", type=float, default=0.5, help="Delay between LEDs (seconds)"
    )
    parser.add_argument(
        "--lock-exposure", action="store_true", help="Try to lock exposure/white balance"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    ws = websocket.WebSocketApp(
        args.ws_url,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=lambda sock: scan_leds(sock, args),
    )
    ws.run_forever()


if __name__ == "__main__":
    main()
