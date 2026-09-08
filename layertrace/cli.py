from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import TraceConfig, trace_image


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="layertrace",
        description="Approximate a flat-color raster image as a back-to-front SVG paint stack.",
    )
    parser.add_argument("input", type=Path, help="opaque PNG or JPEG input")
    parser.add_argument("--colors", type=int, default=32, help="quantization color count")
    parser.add_argument("--underlap", type=int, default=2, help="lower-layer expansion in pixels")
    parser.add_argument("--simplify", type=float, default=1.0, help="Douglas-Peucker epsilon in pixels")
    parser.add_argument("--min-area", type=int, default=4, help="merge connected regions smaller than this")
    parser.add_argument("--smoothing", type=float, default=0.0, help="optional Gaussian sigma")
    parser.add_argument("--ordering", choices=("area", "containment"), default="containment")
    parser.add_argument("--curve-fit", choices=("off", "cubic"), default="off")
    parser.add_argument("--curve-error", type=float, default=1.0, help="maximum cubic fit error in pixels")
    parser.add_argument(
        "--path-batching",
        choices=("off", "consecutive"),
        default="off",
        help="batch consecutive same-style non-overlapping regions",
    )
    parser.add_argument(
        "--batch-safety-margin",
        type=float,
        default=1.0,
        help="non-overlap safety margin for compound path batching",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if (
        args.underlap < 0
        or args.simplify < 0
        or args.min_area < 1
        or args.curve_error <= 0
        or args.batch_safety_margin < 0
    ):
        raise SystemExit(
            "underlap/simplify/batch-safety-margin must be non-negative; "
            "min-area/curve-error must be positive"
        )
    report = trace_image(
        args.input,
        args.output,
        TraceConfig(
            colors=args.colors,
            underlap=args.underlap,
            simplify=args.simplify,
            min_area=args.min_area,
            smoothing=args.smoothing,
            ordering=args.ordering,
            curve_fit=args.curve_fit,
            curve_error=args.curve_error,
            path_batching=args.path_batching,
            batch_safety_margin=args.batch_safety_margin,
        ),
    )
    print(json.dumps(report["metrics"], indent=2))
    return 0
