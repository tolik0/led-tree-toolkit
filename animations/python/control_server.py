import argparse
import asyncio
import json
import logging
import threading
from pathlib import Path

from aiohttp import web
from leds_core import LEDController

from animations import ANIMATIONS

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
DATA_DIR = Path(__file__).resolve().parents[2] / "scanning" / "data"
LOGGER = logging.getLogger(__name__)


def parse_color(value, fallback=(255, 40, 10)):
    if not value or not isinstance(value, str):
        return fallback
    value = value.lstrip("#")
    if len(value) != 6:
        return fallback
    try:
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return fallback


def parse_float(params, key, default):
    value = params.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_int(params, key, default):
    value = params.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def build_anim_params(name, params):
    if name == "sphere":
        return {
            "transition_time": parse_float(params, "transition_time", 2.0),
            "color_step": parse_int(params, "color_step", 20),
        }
    if name == "radial_pulse":
        return {"pulse_speed": parse_float(params, "pulse_speed", 1.0)}
    if name == "flame":
        return {
            "speed": parse_float(params, "speed", 0.2),
            "flicker": parse_float(params, "flicker", 1.0),
            "core_radius": parse_float(params, "core_radius", 100),
            "height_fraction": parse_float(params, "height_fraction", 0.2),
            "base_color": parse_color(params.get("base_color")),
        }
    if name == "mic_bass":
        return {
            "sensitivity": parse_float(params, "sensitivity", 1.0),
            "floor": parse_float(params, "floor", 0.05),
            "base_color": parse_color(params.get("base_color")),
        }
    if name == "mic_spectrum":
        return {
            "bands": parse_int(params, "bands", 8),
            "min_hz": parse_float(params, "min_hz", 80),
            "max_hz": parse_float(params, "max_hz", 4000),
            "sensitivity": parse_float(params, "sensitivity", 1.0),
        }
    if name == "mic_rise":
        return {
            "min_hz": parse_float(params, "min_hz", 40),
            "max_hz": parse_float(params, "max_hz", 180),
            "sensitivity": parse_float(params, "sensitivity", 1.0),
            "edge_softness": parse_float(params, "edge_softness", 0.12),
            "base_color": parse_color(params.get("base_color")),
            "floor": parse_float(params, "floor", 0.03),
            "attack": parse_float(params, "attack", 0.4),
            "release": parse_float(params, "release", 0.12),
        }
    if name == "rainbow":
        return {"color_step": parse_int(params, "color_step", 10)}
    return {}


class PreviewBroadcaster:
    def __init__(self, loop):
        self.loop = loop
        self.clients = set()
        self.lock = asyncio.Lock()

    async def register(self, ws):
        async with self.lock:
            self.clients.add(ws)

    async def unregister(self, ws):
        async with self.lock:
            self.clients.discard(ws)

    def broadcast(self, payload):
        asyncio.run_coroutine_threadsafe(self._broadcast(payload), self.loop)

    async def _broadcast(self, payload):
        if not self.clients:
            return
        dead = []
        for ws in self.clients:
            try:
                await ws.send_bytes(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


class PreviewController:
    def __init__(self, num_leds, esp_controller, broadcaster, brightness=255, close_esp=False):
        self.num_leds = num_leds
        self.esp_controller = esp_controller
        self.broadcaster = broadcaster
        self.brightness = brightness
        self.close_esp = close_esp

    def close(self):
        if self.close_esp and self.esp_controller:
            self.esp_controller.close()

    def send(self, led_colors):
        scale = max(0, min(255, int(self.brightness))) / 255.0
        scaled = [
            (
                int(max(0, min(255, r * scale))),
                int(max(0, min(255, g * scale))),
                int(max(0, min(255, b * scale))),
            )
            for r, g, b in led_colors
        ]

        if self.esp_controller:
            self.esp_controller.send(scaled)

        payload = bytearray(1 + self.num_leds * 3)
        payload[0] = int(max(0, min(255, self.brightness)))
        for i, (r, g, b) in enumerate(scaled):
            offset = 1 + i * 3
            payload[offset] = r
            payload[offset + 1] = g
            payload[offset + 2] = b
        if self.broadcaster:
            self.broadcaster.broadcast(bytes(payload))


class AnimationRunner:
    def __init__(self, loop):
        self.loop = loop
        self.thread = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.broadcaster = PreviewBroadcaster(loop)
        self.current_name = None
        self.settings = {}
        self.esp_controller = None
        self.esp_config = None
        self.esp_lock = threading.Lock()

    def update_settings(self, settings):
        with self.lock:
            self.settings.update(settings)

    def apply_settings(self, settings):
        with self.lock:
            self.settings.update(settings)
            name = self.current_name
        if name:
            self.start(name, dict(self.settings))

    def stop(self):
        thread = None
        with self.lock:
            if self.thread and self.thread.is_alive():
                self.stop_event.set()
                thread = self.thread
            self.thread = None
        if thread:
            thread.join(timeout=2.0)
        with self.lock:
            self.stop_event = threading.Event()

    def start(self, name, settings):
        self.stop()
        with self.lock:
            self.current_name = name
            self.settings = dict(settings)
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def _ensure_esp_controller(self, num_leds, esp_ws_url, led_order):
        target = (num_leds, esp_ws_url, led_order)
        with self.esp_lock:
            if not esp_ws_url:
                if self.esp_controller:
                    self.esp_controller.close()
                self.esp_controller = None
                self.esp_config = None
                return None
            if self.esp_controller and self.esp_config == target:
                return self.esp_controller
            if self.esp_controller:
                self.esp_controller.close()
                self.esp_controller = None
                self.esp_config = None
            try:
                controller = LEDController(
                    num_leds=num_leds, ws_url=esp_ws_url, led_order=led_order
                )
                controller.connect()
            except Exception:
                return None
            self.esp_controller = controller
            self.esp_config = target
            return controller

    def shutdown(self):
        self.stop()
        with self.esp_lock:
            if self.esp_controller:
                self.esp_controller.close()
            self.esp_controller = None
            self.esp_config = None

    def _run(self):
        with self.lock:
            settings = dict(self.settings)
            current_name = self.current_name
            stop_event = self.stop_event

        num_leds = settings.get("led_count", 400)
        esp_ws_url = settings.get("esp_ws_url")
        brightness = settings.get("brightness", 255)
        led_order = settings.get("led_order")
        params = settings.get("params", {})

        frame_delay = parse_float(settings, "frame_delay", 0.02)
        frame_delay = max(0.001, frame_delay)

        anim_params = {"frame_delay": frame_delay, "stop_event": stop_event}
        anim_params.update(build_anim_params(current_name, params))

        esp_controller = self._ensure_esp_controller(num_leds, esp_ws_url, led_order)

        proxy = PreviewController(num_leds, esp_controller, self.broadcaster, brightness=brightness)
        try:
            anim = ANIMATIONS[current_name](**anim_params)
            anim.run(proxy)
        except Exception:
            LOGGER.exception("Animation runner failed for '%s'", current_name)
        finally:
            proxy.close()


async def handle_index(request):
    return web.FileResponse(WEB_DIR / "index.html")


async def handle_coords(request):
    preferred = WEB_DIR / "coords.txt"
    if preferred.exists():
        return web.FileResponse(preferred)
    for fallback_name in ("led_coordinates_3d_clean.txt", "led_coordinates_fixed_new.txt"):
        fallback = DATA_DIR / fallback_name
        if fallback.exists():
            return web.FileResponse(fallback)
    raise web.HTTPNotFound()


async def handle_control(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    runner = request.app["runner"]

    async for msg in ws:
        if msg.type == web.WSMsgType.TEXT:
            try:
                payload = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            action = payload.get("action")
            if action == "start":
                name = payload.get("name")
                if name not in ANIMATIONS:
                    continue
                runner.start(name, payload)
            elif action == "stop":
                runner.stop()
            elif action == "set":
                runner.apply_settings(payload)
            await ws.send_str(json.dumps({"status": "ok"}))
        elif msg.type == web.WSMsgType.ERROR:
            break

    return ws


async def handle_preview(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    broadcaster = request.app["runner"].broadcaster
    await broadcaster.register(ws)
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.ERROR:
                break
    finally:
        await broadcaster.unregister(ws)
    return ws


async def on_startup(app):
    runner = app["runner"]
    loop = asyncio.get_running_loop()
    runner.loop = loop
    runner.broadcaster.loop = loop


async def on_cleanup(app):
    app["runner"].shutdown()


def build_app(loop):
    app = web.Application()
    app["runner"] = AnimationRunner(loop)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.router.add_get("/", handle_index)
    app.router.add_get("/coords.txt", handle_coords)
    app.router.add_get("/control", handle_control)
    app.router.add_get("/preview", handle_preview)
    app.router.add_static("/", WEB_DIR)
    return app


def parse_args():
    parser = argparse.ArgumentParser(description="Run local animation control server.")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port to serve the web UI")
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = build_app(loop)
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
