# ESP32-C6 WebSocket WS2811 Firmware

This firmware exposes `/ws` and accepts binary LED frames for a WS2811 strip.

## Protocol
- `3 * LED_COUNT` bytes: `RGBRGB...`
- Optional brightness prefix: `1 + (3 * LED_COUNT)` bytes

## Build And Flash From Scratch

### 1. Prerequisites
- ESP32-C6 board
- USB data cable (not charge-only)
- ESP-IDF installed locally

If ESP-IDF is not installed yet (Linux/macOS example):

```bash
mkdir -p ~/esp
cd ~/esp
git clone --recursive https://github.com/espressif/esp-idf.git
cd esp-idf
./install.sh esp32c6
```

Activate ESP-IDF environment in every new shell:

```bash
cd ~/esp/esp-idf
. ./export.sh
```

### 2. Open The Firmware Project

```bash
cd /path/to/leds/firmware/firmware_esp32c6_ws2811
```

### 3. Select Chip Target (one-time per build directory)

```bash
idf.py set-target esp32c6
```

### 4. Configure Device Settings

```bash
idf.py menuconfig
```

Set:
- `LED Controller -> WiFi SSID`
- `LED Controller -> WiFi Password`
- `LED Controller -> LED strip GPIO`
- `LED Controller -> LED count`
- `LED Controller -> LED pixel format`

Save and exit.

### 5. Build

```bash
idf.py build
```

### 6. Find Serial Port

Typical Linux device names:

```bash
ls /dev/ttyACM* /dev/ttyUSB* 2>/dev/null
```

Use the correct port in the next command (example: `/dev/ttyACM0`).

### 7. Flash And Open Serial Monitor

```bash
idf.py -p /dev/ttyACM0 flash monitor
```

If the board has old/invalid flash contents, do a full erase once:

```bash
idf.py -p /dev/ttyACM0 erase-flash flash monitor
```

Exit monitor with `Ctrl+]`.

### 8. Verify Boot

On successful boot, the monitor should show normal startup logs and Wi-Fi connection attempts.
After Wi-Fi connects, control clients can connect to:

`ws://<device-ip>/ws`

## Security Note
Do not commit `sdkconfig` because it can include plain-text credentials.
Keep shareable defaults in `sdkconfig.defaults`.
