Scanning Scripts

Purpose
- Capture LED images, triangulate 3D coordinates, and visualize/clean results.

Recommended pipeline
1) capture_led_images.py
   Capture per-LED images for each vantage point.
   Output: scanning/data/led_detections_2d.txt
2) triangulate_no_calibration.py
   Triangulates 3D using a simple pinhole model (no separate calibration step).
   Output: scanning/data/led_coordinates_3d_raw.txt
3) clean_3d_coordinates.py
   Cleans obvious outliers and produces a smoother file.
   Output: scanning/data/led_coordinates_3d_clean.txt
4) plot_led_distances.py / plot_leds_html.py
   Visualize results and spot bad points.

Scripts
- capture_led_images.py
  Drives LEDs and captures images from multiple vantages.
  Use this first to collect per-LED images for each vantage point.
- triangulate_no_calibration.py
  Computes 3D coordinates from the captured images.
  Supports ROI selection, minimum brightness filter, and opposite-view pairing.
- clean_3d_coordinates.py
  Post-process 3D points to remove obvious outliers and optionally fill gaps.
  Example:
    python3 scanning/scripts/clean_3d_coordinates.py --input-file led_coordinates_3d_raw.txt --distance-threshold 55
  Backfill trend (missing start indices):
    python3 scanning/scripts/clean_3d_coordinates.py --input-file led_coordinates_3d_raw.txt --backfill-trend --trend-window 5
- plot_led_distances.py
  Plot inter-LED distances to detect outliers.
- plot_leds_html.py
  3D HTML plot for shareable inspection.

Notes
- All scripts expect data in scanning/data and write outputs to scanning/outputs.
- Set ESP32_IP once per shell:
  source ../../env.sh
