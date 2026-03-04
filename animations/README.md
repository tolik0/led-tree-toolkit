# Animations

Python animation runtime plus a web control UI for streaming frames to ESP32 firmware.

## Key Files
- `animations/python/leds_core.py`: transport and shared animation primitives
- `animations/python/animations.py`: animation implementations and registry
- `animations/python/run_animation.py`: CLI runner
- `animations/python/control_server.py`: local server for the web UI
- `animations/web/`: static frontend assets

## Run From CLI
```bash
source env.sh
source .venv/bin/activate
python animations/python/run_animation.py rainbow
```

Interactive mode:
```bash
python animations/python/run_animation.py
```

## Run Web UI
```bash
source .venv/bin/activate
python animations/python/control_server.py --host 0.0.0.0 --port 8080
```
Then open `http://<your-computer-ip>:8080`.

## Notes
- The browser controls the local Python server.
- The Python server optionally forwards frames to ESP32 over WebSocket.
- Coordinate preview uses data from `scanning/data/led_coordinates_3d_clean.txt`.
