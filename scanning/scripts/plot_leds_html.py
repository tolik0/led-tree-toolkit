"""Generate a shareable HTML plot of 3D LED coordinates.

This script parses the LED coordinate file (supports plain floats and numpy
array text) and produces an interactive Plotly HTML file with labels so you
can inspect points in the browser.
"""

import argparse
import re
from pathlib import Path

import plotly.graph_objects as go

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs"


def parse_coord_string(value):
    """Parse a coordinate tuple from either plain floats or numpy array repr."""
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


def parse_led_line(line):
    """Parse a line like 'LED 0: (x, y, z)' and return (idx, (x, y, z))."""
    parts = line.strip().split(": ")
    if len(parts) != 2:
        return None
    led_index = int(parts[0].split()[1])
    coords = parse_coord_string(parts[1])
    if coords is None:
        return None
    return led_index, coords


def load_coordinates(filename):
    """Load 3D coordinates from a file and keep LED indices."""
    coordinates = []
    with open(filename, "r") as file:
        for line in file:
            parsed = parse_led_line(line)
            if parsed:
                coordinates.append(parsed)
    return coordinates


def plot_coordinates_to_html(coordinates, output_filename):
    """Plot 3D coordinates and save to an HTML file."""
    led_indices, xyz_coords = zip(*coordinates)
    x_coords = [coord[0] for coord in xyz_coords]
    y_coords = [coord[1] for coord in xyz_coords]
    z_coords = [coord[2] for coord in xyz_coords]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter3d(
            x=x_coords,
            y=y_coords,
            z=z_coords,
            mode="markers+text+lines",
            marker=dict(size=5, color="blue"),
            line=dict(color="blue", width=2),
            text=[str(idx) for idx in led_indices],
            textposition="top center",
        )
    )

    fig.update_layout(
        title="LED Positions with Connections",
        scene=dict(
            xaxis_title="X Coordinate",
            yaxis_title="Y Coordinate",
            zaxis_title="Z Coordinate",
        ),
        margin=dict(l=0, r=0, b=0, t=40),
    )

    fig.write_html(output_filename)
    print(f"3D plot saved to {output_filename}")


def parse_args():
    """Parse CLI args for HTML plotting."""
    parser = argparse.ArgumentParser(description="Plot 3D coordinates to HTML.")
    parser.add_argument(
        "--input-file", default="led_coordinates_3d_clean.txt", help="Input file in scanning/data/"
    )
    parser.add_argument(
        "--output-file",
        default="led_coordinates_3d_plot.html",
        help="Output file in scanning/outputs/",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    output_path = OUTPUT_DIR / args.output_file
    output_path.parent.mkdir(parents=True, exist_ok=True)

    coordinates = load_coordinates(DATA_DIR / args.input_file)
    plot_coordinates_to_html(coordinates, output_path)


if __name__ == "__main__":
    main()
