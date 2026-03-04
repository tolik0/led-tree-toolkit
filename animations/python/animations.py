import math
import random
import threading
import time

import numpy as np
from leds_core import (
    DATA_DIR,
    Animation,
    CoordinateAnimation,
    LEDController,
    color_wheel,
    resolve_num_leds,
)

COORDS_CANDIDATES = [
    "led_coordinates_3d_clean.txt",
    "led_coordinates_fixed_new.txt",
]
EPSILON = 1e-6


def resolve_coords_file():
    for filename in COORDS_CANDIDATES:
        candidate = DATA_DIR / filename
        if candidate.exists():
            return candidate
    return DATA_DIR / COORDS_CANDIDATES[0]


COORDS_FIXED = resolve_coords_file()


def clamp(value, min_value=0.0, max_value=1.0):
    return max(min_value, min(max_value, value))


def scale_color(color, scale):
    r, g, b = color
    return (int(r * scale), int(g * scale), int(b * scale))


class AnimationRegistry:
    def __init__(self):
        self._animations = {}
        self._descriptions = {}

    def register(self, cls):
        name = cls.name
        description = cls.description
        if not name:
            raise ValueError("Animation must define a name.")
        self._animations[name] = cls
        if description:
            self._descriptions[name] = description
        return cls

    @property
    def animations(self):
        return dict(self._animations)

    @property
    def descriptions(self):
        return dict(self._descriptions)


REGISTRY = AnimationRegistry()


def register_animation(cls):
    return REGISTRY.register(cls)


class PeakTracker:
    """Track a rolling peak with exponential decay."""

    def __init__(self, decay=0.98, floor=EPSILON):
        self.decay = decay
        self.peak = floor

    def update(self, value):
        self.peak = max(value, self.peak * self.decay)
        return self.peak


class AttackReleaseSmoother:
    """Smooth values with different attack/release rates."""

    def __init__(self, attack=0.4, release=0.12, initial=0.0):
        self.attack = attack
        self.release = release
        self.value = initial

    def update(self, target):
        alpha = self.attack if target > self.value else self.release
        self.value = self.value * (1.0 - alpha) + target * alpha
        return self.value


class AudioReactiveMixin:
    """Template method for audio-driven animations."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def run(self, controller):
        with AudioInput() as audio:
            self.run_with_audio(controller, audio)

    def run_with_audio(self, controller, audio):
        raise NotImplementedError


@register_animation
class RainbowAnimation(Animation):
    """Classic rainbow cycle across LED indices.

    Params:
    - color_step: color increment per frame.
    """

    name = "rainbow"
    description = "Classic rainbow cycle across LED indices."

    def __init__(self, color_step=10, frame_delay=None, stop_event=None):
        super().__init__(frame_delay=frame_delay, stop_event=stop_event)
        self.color_step = color_step

    def run(self, controller):
        # Sweep a rainbow across LED indices with a moving phase offset.
        while True:
            if self.should_stop():
                return
            frames_per_cycle = 256 // self.color_step
            for frame in range(frames_per_cycle):
                if self.should_stop():
                    return
                led_colors = []
                for i in range(controller.num_leds):
                    wheel_pos = (i + frame * self.color_step) % 256
                    led_colors.append(color_wheel(wheel_pos))
                # Push a full frame to the strip.
                controller.send(led_colors)
                time.sleep(self.frame_delay)


class AudioInput:
    """Microphone audio capture helper for music-reactive animations."""

    def __init__(self, sample_rate=44100, block_size=1024, channels=1):
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("sounddevice is required for microphone animations.") from exc

        self.sd = sd
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.channels = channels
        self._lock = threading.Lock()
        self._buffer = np.zeros(self.block_size, dtype=np.float32)
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            blocksize=self.block_size,
            dtype="float32",
            callback=self._callback,
        )
        self._window = np.hanning(self.block_size).astype(np.float32)
        self._freqs = np.fft.rfftfreq(self.block_size, 1.0 / self.sample_rate)

    def _callback(self, indata, frames, time_info, status):
        if status:
            return
        data = indata[:, 0].copy()
        with self._lock:
            self._buffer = data

    def start(self):
        self._stream.start()

    def stop(self):
        self._stream.stop()
        self._stream.close()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop()

    def spectrum(self):
        with self._lock:
            samples = self._buffer.copy()
        windowed = samples * self._window
        fft = np.fft.rfft(windowed)
        return np.abs(fft), self._freqs

    def band_level(self, min_hz, max_hz):
        spectrum, freqs = self.spectrum()
        mask = (freqs >= min_hz) & (freqs <= max_hz)
        if not np.any(mask):
            return 0.0
        return float(np.mean(spectrum[mask]))

    def band_levels(self, min_hz, max_hz, bands):
        spectrum, freqs = self.spectrum()
        mask = (freqs >= min_hz) & (freqs <= max_hz)
        if not np.any(mask):
            return [0.0] * bands
        band_spectrum = spectrum[mask]
        split = np.array_split(band_spectrum, bands)
        return [float(np.mean(chunk)) if len(chunk) else 0.0 for chunk in split]


@register_animation
class SphereGrowthAnimation(CoordinateAnimation):
    """Growing colored spheres from the center.

    Params:
    - transition_time: seconds per growth cycle.
    - color_step: hue step per cycle.
    """

    name = "sphere"
    description = "Growing colored spheres from the center."
    coords_file = COORDS_FIXED

    def __init__(self, transition_time=2, color_step=20, frame_delay=None, stop_event=None):
        super().__init__(
            coords_file=self.coords_file, frame_delay=frame_delay, stop_event=stop_event
        )
        self.transition_time = max(0.1, float(transition_time))
        self.color_step = max(1, int(color_step))

    def run(self, controller):
        # Expand a colored sphere from the center, then switch to the next color.
        x_coords = [x for _, (x, _, _) in self.coords]
        y_coords = [y for _, (_, y, _) in self.coords]
        z_coords = [z for _, (_, _, z) in self.coords]
        center = (np.mean(x_coords), np.mean(y_coords), np.mean(z_coords))
        distances = [
            math.sqrt((x - center[0]) ** 2 + (y - center[1]) ** 2 + (z - center[2]) ** 2)
            for x, y, z in zip(x_coords, y_coords, z_coords)
        ]
        max_distance = max(max(distances), EPSILON)
        indexed_distances = []
        for (led_index, _), dist in zip(self.coords, distances):
            if 0 <= led_index < controller.num_leds:
                indexed_distances.append((led_index, dist))
        current_colors = [(0, 0, 0)] * controller.num_leds
        hue = 0
        while True:
            if self.should_stop():
                return
            total_frames = max(1, int(round(self.transition_time / max(self.frame_delay, EPSILON))))
            color = color_wheel(hue % 256)
            for frame in range(total_frames):
                if self.should_stop():
                    return
                led_colors = current_colors[:]
                progress = frame / max(total_frames - 1, 1)
                for led_index, dist in indexed_distances:
                    # Light LEDs whose distance from center is within the sphere radius.
                    if dist / max_distance <= progress:
                        led_colors[led_index] = color
                controller.send(led_colors)
                time.sleep(self.frame_delay)
            current_colors = led_colors
            hue = (hue + self.color_step) % 256


@register_animation
class MicBassPulseAnimation(AudioReactiveMixin, Animation):
    """Pulse the tree based on bass energy from the microphone.

    Params:
    - sensitivity: scale factor for bass response.
    - base_color: RGB color for the pulse.
    - floor: minimum brightness fraction.
    """

    name = "mic_bass"
    description = "Bass-driven pulse using microphone input."

    def __init__(
        self,
        sensitivity=1.0,
        base_color=(255, 40, 10),
        floor=0.05,
        frame_delay=None,
        stop_event=None,
    ):
        super().__init__(frame_delay=frame_delay, stop_event=stop_event)
        self.sensitivity = sensitivity
        self.base_color = base_color
        self.floor = floor

    def run_with_audio(self, controller, audio):
        peak = PeakTracker(decay=0.98)
        while True:
            if self.should_stop():
                return
            level = audio.band_level(40, 180)
            max_level = peak.update(level)
            intensity = (level / (max_level + EPSILON)) * self.sensitivity
            intensity = clamp(intensity, self.floor, 1.0)
            color = scale_color(self.base_color, intensity)
            controller.send([color] * controller.num_leds)
            time.sleep(self.frame_delay)


@register_animation
class MicSpectrumAnimation(AudioReactiveMixin, CoordinateAnimation):
    """Map FFT bands from microphone audio across the tree height.

    Params:
    - bands: number of spectrum bands.
    - min_hz: lowest frequency to consider.
    - max_hz: highest frequency to consider.
    - sensitivity: scale factor for band response.
    """

    name = "mic_spectrum"
    description = "Spectrum bands mapped over tree height using microphone input."
    coords_file = COORDS_FIXED

    def __init__(
        self, bands=8, min_hz=80, max_hz=4000, sensitivity=1.0, frame_delay=None, stop_event=None
    ):
        super().__init__(
            coords_file=self.coords_file, frame_delay=frame_delay, stop_event=stop_event
        )
        self.bands = bands
        self.min_hz = min_hz
        self.max_hz = max_hz
        self.sensitivity = sensitivity
        ys = [coord[1] for _, coord in self.coords]
        self.ymin, self.ymax = min(ys), max(ys)
        span = max(self.ymax - self.ymin, EPSILON)
        self.band_map = []
        for led_index, (_, y, _) in self.coords:
            t = (y - self.ymin) / span
            band = min(self.bands - 1, max(0, int(t * self.bands)))
            self.band_map.append((led_index, band))
        self.band_colors = [
            color_wheel(int((band / max(self.bands - 1, 1)) * 255)) for band in range(self.bands)
        ]

    def run_with_audio(self, controller, audio):
        peaks = [PeakTracker(decay=0.98) for _ in range(self.bands)]
        smooth = [0.0] * self.bands
        while True:
            if self.should_stop():
                return
            levels = audio.band_levels(self.min_hz, self.max_hz, self.bands)
            for i, level in enumerate(levels):
                max_level = peaks[i].update(level)
                value = (level / (max_level + EPSILON)) * self.sensitivity
                value = clamp(value, 0.0, 1.0)
                smooth[i] = smooth[i] * 0.7 + value * 0.3

            led_colors = [(0, 0, 0)] * controller.num_leds
            for led_index, band in self.band_map:
                intensity = smooth[band]
                led_colors[led_index] = scale_color(self.band_colors[band], intensity)
            controller.send(led_colors)
            time.sleep(self.frame_delay)


@register_animation
class MicRiseAnimation(AudioReactiveMixin, CoordinateAnimation):
    """Raise a solid color band from the base using bass energy.

    Params:
    - min_hz: lowest frequency to consider.
    - max_hz: highest frequency to consider.
    - sensitivity: scale factor for response.
    - edge_softness: height fraction for softened top edge.
    - base_color: RGB color for the rise.
    - floor: minimum height fraction to keep lit.
    - attack: rise smoothing factor.
    - release: fall smoothing factor.
    """

    name = "mic_rise"
    description = "Bass-reactive rise from the base in a single color."
    coords_file = COORDS_FIXED

    def __init__(
        self,
        min_hz=40,
        max_hz=180,
        sensitivity=1.0,
        edge_softness=0.12,
        base_color=(255, 40, 10),
        floor=0.03,
        attack=0.4,
        release=0.12,
        frame_delay=None,
        stop_event=None,
    ):
        super().__init__(
            coords_file=self.coords_file, frame_delay=frame_delay, stop_event=stop_event
        )
        self.min_hz = min_hz
        self.max_hz = max_hz
        self.sensitivity = sensitivity
        self.edge_softness = edge_softness
        self.base_color = base_color
        self.floor = floor
        self.attack = attack
        self.release = release
        ys = [coord[1] for _, coord in self.coords]
        self.ymin, self.ymax = min(ys), max(ys)
        span = max(self.ymax - self.ymin, EPSILON)
        self.height_map = []
        for led_index, (_, y, _) in self.coords:
            t = (self.ymax - y) / span
            self.height_map.append((led_index, t))

    def run_with_audio(self, controller, audio):
        peak = PeakTracker(decay=0.98)
        smoother = AttackReleaseSmoother(
            attack=self.attack, release=self.release, initial=self.floor
        )
        baseline = 0.0
        edge = max(self.edge_softness, EPSILON)
        while True:
            if self.should_stop():
                return
            level = audio.band_level(self.min_hz, self.max_hz)
            baseline = baseline * 0.995 + level * 0.005
            max_level = peak.update(level)
            span_level = max(max_level - baseline, EPSILON)
            target = ((level - baseline) / span_level) * self.sensitivity
            target = clamp(target, 0.0, 1.0)
            height = clamp(smoother.update(target), self.floor, 1.0)

            led_colors = [(0, 0, 0)] * controller.num_leds
            for led_index, t in self.height_map:
                if t > height + edge:
                    continue
                if t <= height:
                    intensity = 1.0
                else:
                    intensity = 1.0 - (t - height) / edge
                led_colors[led_index] = scale_color(self.base_color, intensity * height)
            controller.send(led_colors)
            time.sleep(self.frame_delay)


@register_animation
class RadialPulseAnimation(CoordinateAnimation):
    """Pulses expanding from random points.

    Params:
    - pulse_speed: radius increment per frame.
    """

    name = "radial_pulse"
    description = "Pulses expanding from random points."
    coords_file = COORDS_FIXED

    def __init__(self, pulse_speed=1.0, frame_delay=None, stop_event=None):
        super().__init__(
            coords_file=self.coords_file, frame_delay=frame_delay, stop_event=stop_event
        )
        self.pulse_speed = pulse_speed

    def run(self, controller):
        # Emit ring pulses with a trailing decay so old rings fade smoothly.
        coords = [np.array(coord) for _, coord in self.coords]
        center_mean = np.mean(coords, axis=0)
        tree_radius = max(np.linalg.norm(point - center_mean) for point in coords)
        ring_width = tree_radius * 0.05
        max_dist = max(tree_radius * 2, EPSILON)

        trail = PulseTrail(controller.num_leds, decay=0.92, glow=(8, 2, 1))
        while True:
            if self.should_stop():
                return
            center = random.choice(coords)
            for frame in self._pulse_frames(center, coords, max_dist, ring_width):
                if self.should_stop():
                    return
                trail.decay()
                ring_color, ring_hits = frame
                trail.apply_ring(ring_color, ring_hits)
                controller.send(trail.render())
                time.sleep(self.frame_delay)

    def _pulse_frames(self, center, coords, max_dist, ring_width):
        """Yield (ring_color, ring_hits) for each radius step of a pulse."""
        radius = 0.0
        while radius < max_dist:
            ring_color = color_wheel(int((radius / max_dist) * 255) % 256)
            ring_hits = {}
            for led_index, coord in self.coords:
                dist = np.linalg.norm(np.array(coord) - center)
                band = ring_width - abs(dist - radius)
                if band <= 0:
                    continue
                ring_hits[led_index] = band / ring_width
            yield ring_color, ring_hits
            radius += self.pulse_speed


class PulseTrail:
    """Track per-LED trail color and intensity for radial pulses."""

    def __init__(self, num_leds, decay=0.92, glow=(8, 2, 1)):
        self.decay_factor = decay
        self.glow = glow
        self.colors = [(0, 0, 0)] * num_leds
        self.strength = [0.0] * num_leds

    def decay(self):
        """Apply exponential decay to existing trail strength."""
        self.strength = [value * self.decay_factor for value in self.strength]

    def apply_ring(self, ring_color, ring_hits):
        """Merge the current ring into the trail with max-intensity blending."""
        for led_index, intensity in ring_hits.items():
            if intensity > self.strength[led_index]:
                self.strength[led_index] = intensity
                self.colors[led_index] = ring_color

    def render(self):
        """Render the trail into per-LED RGB values."""
        output = []
        for (r, g, b), strength in zip(self.colors, self.strength):
            output.append(
                (
                    int(max(r * strength, self.glow[0])),
                    int(max(g * strength, self.glow[1])),
                    int(max(b * strength, self.glow[2])),
                )
            )
        return output


@register_animation
class FlameAnimation(CoordinateAnimation):
    """Flickering flame gradient from bottom to top.

    Params:
    - speed: flicker speed.
    - flicker: flicker intensity.
    - core_radius: radius of the flame core.
    - height_fraction: portion of tree used for flame base.
    - base_color: base RGB color for the flame (defaults to red/orange).
    """

    name = "flame"
    description = "Flickering flame gradient from bottom to top."
    coords_file = COORDS_FIXED

    def __init__(
        self,
        speed=0.2,
        flicker=1.0,
        core_radius=100,
        height_fraction=0.2,
        base_color=(255, 40, 10),
        frame_delay=None,
        stop_event=None,
    ):
        super().__init__(
            coords_file=self.coords_file, frame_delay=frame_delay, stop_event=stop_event
        )
        self.speed = speed
        self.flicker = flicker
        self.core_radius = core_radius
        self.height_fraction = height_fraction
        self.base_color = base_color
        ys = [coord[1] for _, coord in self.coords]
        xs = [coord[0] for _, coord in self.coords]
        zs = [coord[2] for _, coord in self.coords]
        self.ymin, self.ymax = min(ys), max(ys)
        self.xc = sum(xs) / len(xs)
        self.zc = sum(zs) / len(zs)
        self.flame_points = [
            (led_index, y, math.sqrt((x - self.xc) ** 2 + (z - self.zc) ** 2))
            for led_index, (x, y, z) in self.coords
        ]

    def run(self, controller):
        # Flickering flame gradient near the base with radial falloff.
        phase = 0.0
        span = max(self.ymax - self.ymin, EPSILON)
        base_top = self.ymax - span * self.height_fraction
        while True:
            if self.should_stop():
                return
            led_colors = [(0, 0, 0)] * controller.num_leds
            for led_index, y, r_dist in self.flame_points:
                if y < base_top:
                    continue
                t = (self.ymax - y) / max(self.ymax - base_top, EPSILON)
                # Core fades with radius; noise adds flicker.
                core = max(0.0, 1.0 - (r_dist / max(self.core_radius, EPSILON)))
                noise = (math.sin(phase * 2 + y * 0.6 + r_dist * 0.12) + 1) * 0.5
                base_falloff = 1.0 - t
                base = base_falloff * core
                heat = max(0.0, min(1.0, base * (0.35 + self.flicker * noise)))
                # Map heat to a warm flame palette.
                r = int(self.base_color[0] * heat)
                g = int(self.base_color[1] * (heat**2.1))
                b = int(self.base_color[2] * (heat**3))
                led_colors[led_index] = (r, g, b)
            controller.send(led_colors)
            phase += self.speed
            time.sleep(self.frame_delay)


ANIMATIONS = REGISTRY.animations
ANIMATION_DESCRIPTIONS = REGISTRY.descriptions


def run_animation(name):
    if name not in ANIMATIONS:
        raise ValueError(f"Unknown animation: {name}")
    controller = LEDController(num_leds=resolve_num_leds())
    controller.connect()
    try:
        anim = ANIMATIONS[name]()
        anim.run(controller)
    finally:
        controller.close()
