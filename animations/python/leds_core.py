import os
import re
from pathlib import Path

from websocket import create_connection

DATA_DIR = Path(__file__).resolve().parents[2] / "scanning" / "data"


def resolve_ws_url():
    ws_url = os.getenv("ESP32_WS_URL")
    if ws_url:
        return ws_url
    ip = os.getenv("ESP32_IP", "192.168.1.119")
    return f"ws://{ip}/ws"


def resolve_num_leds(default=400):
    value = os.getenv("NUM_LEDS")
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def resolve_frame_delay(default=0.05):
    value = os.getenv("FRAME_DELAY")
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def resolve_led_order(default="RGB"):
    value = os.getenv("LED_ORDER", default)
    value = value.strip().upper()
    if len(value) != 3 or any(c not in "RGB" for c in value):
        return default
    return value


def color_wheel(pos):
    if pos < 85:
        return (pos * 3, 255 - pos * 3, 0)
    if pos < 170:
        pos -= 85
        return (255 - pos * 3, 0, pos * 3)
    pos -= 170
    return (0, pos * 3, 255 - pos * 3)


def parse_coord_string(value):
    if "array" in value:
        array_parts = re.findall(r"\[([^\]]+)\]", value)
        coords = []
        for part in array_parts[:3]:
            nums = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", part)
            if not nums:
                return None
            coords.append(float(nums[0]))
        if len(coords) == 3:
            return tuple(coords)
        return None
    numbers = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", value)
    if len(numbers) < 3:
        return None
    return (float(numbers[0]), float(numbers[1]), float(numbers[2]))


def load_coordinates(filename):
    coordinates = []
    with open(filename, "r") as file:
        for line in file:
            parts = line.strip().split(": ")
            if len(parts) == 2 and parts[0].startswith("LED "):
                led_index = int(parts[0].split()[1])
                coords = parse_coord_string(parts[1])
                if coords is None:
                    continue
                coordinates.append((led_index, coords))
    return coordinates


class LEDController:
    def __init__(self, num_leds, ws_url=None, led_order=None):
        self.num_leds = num_leds
        self.ws_url = ws_url or resolve_ws_url()
        self.led_order = resolve_led_order() if led_order is None else led_order
        self.ws = None

    def connect(self):
        self.ws = create_connection(self.ws_url)

    def close(self):
        if self.ws:
            self.ws.close()
            self.ws = None

    def send(self, led_colors):
        data = bytearray(3 * self.num_leds)
        order_map = {"R": 0, "G": 1, "B": 2}
        order = [order_map[c] for c in self.led_order]
        for i, (r, g, b) in enumerate(led_colors):
            offset = i * 3
            channels = [r, g, b]
            data[offset + 0] = max(0, min(255, int(channels[order[0]])))
            data[offset + 1] = max(0, min(255, int(channels[order[1]])))
            data[offset + 2] = max(0, min(255, int(channels[order[2]])))
        self.ws.send(data, opcode=0x2)


class Animation:
    name = "animation"
    description = ""
    is_3d = False

    def __init__(self, frame_delay=None, stop_event=None):
        self.frame_delay = resolve_frame_delay() if frame_delay is None else frame_delay
        self.stop_event = stop_event

    def should_stop(self):
        return self.stop_event is not None and self.stop_event.is_set()

    def run(self, controller):
        raise NotImplementedError


class CoordinateAnimation(Animation):
    coords_file = None
    is_3d = True

    def __init__(self, coords_file=None, frame_delay=None, stop_event=None):
        super().__init__(frame_delay=frame_delay, stop_event=stop_event)
        self.coords_file = coords_file or self.coords_file
        if self.coords_file is None:
            raise ValueError("coords_file is required for CoordinateAnimation")
        self.coords = load_coordinates(self.coords_file)
