"""
Command-line interface for Retrogaze.

Usage
-----
    python -m retrogaze input.png --size 16x16 --type sprite --output output.png
"""

from __future__ import annotations

import argparse
import json
import sys

from .enforce import enforce_constraints


def _parse_size(value: str) -> tuple[int, int]:
    """Parse a '16x16' size string into an (int, int) tuple."""
    try:
        w_str, h_str = value.lower().split("x")
        return int(w_str), int(h_str)
    except (ValueError, AttributeError):
        raise argparse.ArgumentTypeError(
            f"Invalid size '{value}'. Expected format: WxH (e.g. 16x16)"
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="retrogaze",
        description="Enforce NES hardware constraints on pixel art images.",
    )
    parser.add_argument("input", help="Path to the source image.")
    parser.add_argument(
        "--size",
        type=_parse_size,
        default=None,
        metavar="WxH",
        help="Target sprite size in pixels (must be multiples of 8, e.g. 16x16).",
    )
    parser.add_argument(
        "--type",
        dest="asset_type",
        default="sprite",
        metavar="TYPE",
        help="Asset type label (default: sprite).",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="Output path for the processed PNG. A companion .json file is "
             "written alongside it.",
    )
    parser.add_argument(
        "--prompt",
        default=None,
        help="Optional generation prompt to embed in metadata.",
    )
    parser.add_argument(
        "--max-colors",
        type=int,
        default=4,
        dest="max_colors",
        help="Maximum unique colors per 8×8 tile (default: 4).",
    )

    args = parser.parse_args(argv)

    report = enforce_constraints(
        image_path=args.input,
        target_size=args.size,
        asset_type=args.asset_type,
        output_path=args.output,
        prompt=args.prompt,
        max_colors_per_tile=args.max_colors,
    )

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
