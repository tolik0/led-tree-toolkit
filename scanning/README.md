# Scanning and Coordinates

Tools and data for deriving 3D LED coordinates from multi-view captures.

## Folders
- `scanning/scripts/`: capture, triangulation, cleanup, plotting
- `scanning/data/`: shareable coordinate files
- `scanning/captures/`: local capture dumps (ignored)
- `scanning/outputs/`: generated plots/html (ignored)

## Typical Flow
1. Capture images for each vantage point
2. Triangulate 3D points
3. Clean outliers / fill missing points
4. Feed `scanning/data/led_coordinates_3d_clean.txt` into animations

## How to Scan (Capture Stage)
1. Place the camera on a stable mount and keep it in the same physical position for the full scan.
2. Keep camera settings fixed (focus/exposure/white balance) so brightness is consistent.
3. Start the capture script:
   ```bash
   python3 scanning/scripts/capture_led_images.py --vantage-points 4 --num-leds 400
   ```
4. When prompted for each vantage point, rotate the tree (not the camera) by 90 degrees:
   - vantage 0: 0°
   - vantage 1: 90°
   - vantage 2: 180°
   - vantage 3: 270°
5. Press Enter after each rotation to continue capture.

See `scanning/scripts/README.md` for command details.
