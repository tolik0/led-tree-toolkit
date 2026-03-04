# LED Tree Toolkit

A hardware + software toolkit for driving a WS2811 LED tree with an ESP32 and generating 3D LED coordinates from camera captures.

## Demo

https://github.com/user-attachments/assets/f4afd461-0853-403f-93ae-7eaa4f427318

## What is in this repo
- `firmware/`: ESP-IDF firmware exposing `ws://<device>/ws` for binary LED frames.
- `animations/`: Python animation engine and browser-based control UI.
- `scanning/`: Python tools for capture processing, triangulation, and coordinate cleanup.

## Quick Start
1. Create a virtual environment and install Python dependencies:
   ```bash
   ./venv_setup.sh
   source .venv/bin/activate
   ```
2. Set runtime environment values:
   ```bash
   cp env.example.sh env.sh
   source env.sh
   ```
3. Flash firmware (see `firmware/firmware_esp32c6_ws2811/README.md`).
4. Start control server:
   ```bash
   python animations/python/control_server.py --host 0.0.0.0 --port 8080
   ```
5. Open `http://<your-computer-ip>:8080` and start an animation.

## CLI Animation Runner
Run from repository root:
```bash
python animations/python/run_animation.py rainbow
```

Interactive picker:
```bash
python animations/python/run_animation.py
```

## Coordinate Pipeline
Typical flow:
1. Capture per-vantage LED images
2. Triangulate rough 3D points
3. Clean/repair coordinates
4. Use `scanning/data/led_coordinates_3d_clean.txt` for animations

Detailed script usage is in `scanning/scripts/README.md`.

## Development
Install developer tools:
```bash
pip install pre-commit ruff
pre-commit install
```

Run checks:
```bash
ruff format animations/python scanning/scripts
ruff check animations/python scanning/scripts
```
