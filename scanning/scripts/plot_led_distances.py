"""Plot distances between consecutive LEDs to spot outliers.

This script parses a 3D coordinate file, computes distances between neighboring
LED indices, sorts them, and writes a PNG plot so spikes are easy to see.
"""

import argparse
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs"


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


def calculate_distances(coords):
    """Compute distances between consecutive LEDs."""
    distances = []
    for i in range(1, len(coords)):
        _, coord1 = coords[i - 1]
        _, coord2 = coords[i]
        distances.append(euclidean_distance(coord1, coord2))
    return distances


def parse_args():
    """Parse CLI args for distance plotting."""
    parser = argparse.ArgumentParser(description="Plot sorted distances between LEDs.")
    parser.add_argument(
        "--input-file", default="led_coordinates_3d_clean.txt", help="Input file in scanning/data/"
    )
    parser.add_argument(
        "--output-file",
        default="led_consecutive_distances.png",
        help="Output file in scanning/outputs/",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    output_path = OUTPUT_DIR / args.output_file
    output_path.parent.mkdir(parents=True, exist_ok=True)

    coords = load_coordinates(DATA_DIR / args.input_file)
    distances = calculate_distances(coords)
    sorted_distances = sorted(distances)

    plt.figure(figsize=(10, 6))
    plt.plot(sorted_distances, marker="o", linestyle="-", color="b")
    plt.title("Sorted Distances Between Consecutive LEDs")
    plt.xlabel("LED Pair Index")
    plt.ylabel("Distance")
    plt.grid(True)
    plt.savefig(output_path)


if __name__ == "__main__":
    main()
