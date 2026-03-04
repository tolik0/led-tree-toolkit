"""Clean and fill 3D LED coordinates from text output files.

This script loads an LED coordinate file, optionally fills missing indices, and
repairs outliers by averaging neighbors. It can also backfill missing start
indices before the outlier pass.
"""

import argparse
import re
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def parse_led_line(line):
    """Parse a line like 'LED 0: (x, y, z)' and return (idx, (x, y, z))."""
    parts = line.strip().split(": ")
    if len(parts) != 2:
        return None
    led_index = int(parts[0].split()[1])
    numbers = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", parts[1])
    if len(numbers) < 3:
        return None
    coords = (float(numbers[0]), float(numbers[1]), float(numbers[2]))
    return led_index, coords


def load_coordinates(filename):
    """Load coordinates from a LED coordinate file."""
    coordinates = []
    with open(filename, "r") as file:
        for line in file:
            parsed = parse_led_line(line)
            if parsed:
                coordinates.append(parsed)
    return coordinates


def euclidean_distance(p1, p2):
    """Return Euclidean distance between two 3D points."""
    return float(np.linalg.norm(np.array(p1) - np.array(p2)))


def fill_missing_indices(coords, max_leds):
    """Fill missing LED indices by interpolating between nearest neighbors."""
    coord_map = {idx: coord for idx, coord in coords}
    filled = []
    for idx in range(max_leds):
        if idx in coord_map:
            filled.append((idx, coord_map[idx]))
            continue
        prev_idx = max([i for i in coord_map if i < idx], default=None)
        next_idx = min([i for i in coord_map if i > idx], default=None)
        if prev_idx is None and next_idx is None:
            continue
        if prev_idx is None:
            filled.append((idx, coord_map[next_idx]))
            continue
        if next_idx is None:
            filled.append((idx, coord_map[prev_idx]))
            continue
        prev_coord = np.array(coord_map[prev_idx])
        next_coord = np.array(coord_map[next_idx])
        t = (idx - prev_idx) / (next_idx - prev_idx)
        interp = tuple(prev_coord + t * (next_coord - prev_coord))
        filled.append((idx, interp))
    return filled


def backfill_trend(coords, max_leds, window=5):
    """Fill missing start indices by stepping backward using the average early trend."""
    if not coords:
        return []
    coords_sorted = sorted(coords, key=lambda x: x[0])
    coord_map = {idx: coord for idx, coord in coords_sorted}
    indices = [idx for idx, _ in coords_sorted]
    min_idx = min(indices)
    if min_idx == 0:
        return coords_sorted

    start_seq = []
    for idx in range(min_idx, min_idx + window):
        if idx in coord_map:
            start_seq.append((idx, np.array(coord_map[idx], dtype=float)))
    if len(start_seq) < 2:
        return fill_missing_indices(coords, max_leds)

    deltas = []
    for i in range(1, len(start_seq)):
        deltas.append(start_seq[i][1] - start_seq[i - 1][1])
    avg_delta = np.mean(deltas, axis=0)

    filled = []
    for idx in range(max_leds):
        if idx in coord_map:
            filled.append((idx, coord_map[idx]))
        elif idx < min_idx:
            steps_back = min_idx - idx
            coord = start_seq[0][1] - avg_delta * steps_back
            filled.append((idx, tuple(coord)))
        else:
            continue
    return filled


def fix_coordinates(coords, distance_threshold=55.0):
    """Replace outliers by averaging neighbors if both adjacent distances exceed threshold."""
    fixed_coords = []

    for i in range(len(coords)):
        led_index, (x, y, z) = coords[i]

        # Check the distance to the previous LED
        if i > 0:
            prev_index, prev_coords = coords[i - 1]
            distance_prev = euclidean_distance((x, y, z), prev_coords)
        else:
            distance_prev = 0  # No previous LED

        # Check the distance to the next LED
        if i < len(coords) - 1:
            next_index, next_coords = coords[i + 1]
            distance_next = euclidean_distance((x, y, z), next_coords)
        else:
            distance_next = 0  # No next LED

        # If both neighbors are too far away, average the coordinates
        if distance_prev > distance_threshold and distance_next > distance_threshold:
            # Average the correct neighbors' coordinates
            new_x = (prev_coords[0] + next_coords[0]) / 2
            new_y = (prev_coords[1] + next_coords[1]) / 2
            new_z = (prev_coords[2] + next_coords[2]) / 2
            print(f"Fixed led {led_index} at ({x}, {y}, {z}) -> ({new_x}, {new_y}, {new_z})")
            fixed_coords.append((led_index, (new_x, new_y, new_z)))
        else:
            # If distances are not too far, keep the original coordinates
            fixed_coords.append((led_index, (x, y, z)))

    return fixed_coords


def save_fixed_coordinates_to_file(coords, filename):
    """Save coordinates to a text file using the standard LED format."""
    with open(filename, "w") as file:
        for led_index, (x, y, z) in coords:
            file.write(f"LED {led_index}: ({x}, {y}, {z})\n")


def parse_args():
    """Parse CLI args for coordinate cleanup."""
    parser = argparse.ArgumentParser(description="Fix obvious 3D coordinate outliers.")
    parser.add_argument(
        "--input-file", default="led_coordinates_3d_raw.txt", help="Input file in scanning/data/"
    )
    parser.add_argument(
        "--output-file",
        default="led_coordinates_3d_clean.txt",
        help="Output file in scanning/data/",
    )
    parser.add_argument("--distance-threshold", type=float, default=55.0, help="Outlier threshold")
    parser.add_argument(
        "--fill-missing", action="store_true", help="Fill missing LED indices by interpolation"
    )
    parser.add_argument(
        "--backfill-trend", action="store_true", help="Backfill start indices using average trend"
    )
    parser.add_argument(
        "--trend-window", type=int, default=5, help="Window size for trend backfill"
    )
    parser.add_argument("--num-leds", type=int, default=400, help="Total LED count")
    return parser.parse_args()


def main():
    """Load, fix, and save 3D coordinates."""
    args = parse_args()
    input_path = DATA_DIR / args.input_file
    output_path = DATA_DIR / args.output_file

    coords = load_coordinates(input_path)
    if args.backfill_trend:
        coords = backfill_trend(coords, args.num_leds, window=args.trend_window)
    elif args.fill_missing:
        coords = fill_missing_indices(coords, args.num_leds)
    fixed_coords = fix_coordinates(coords, distance_threshold=args.distance_threshold)
    save_fixed_coordinates_to_file(fixed_coords, output_path)


if __name__ == "__main__":
    main()
