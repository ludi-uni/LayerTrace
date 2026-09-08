"""Evaluate the consecutive-batching safety margin against the 1px baseline."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from time import perf_counter

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from .phase3 import INPUTS
from .phase4 import _svg_streams
from .pipeline import TraceConfig, trace_image


MARGINS = (0.0, 0.5, 1.0, 2.0)


def _margin_name(margin: float) -> str:
    return str(margin).replace(".", "p")


def _run(repo: Path, output: Path, test_id: str, input_path: Path, margin: float) -> dict:
    run_dir = output / test_id / f"margin_{_margin_name(margin)}"
    started = perf_counter()
    report = trace_image(
        repo / input_path,
        run_dir,
        TraceConfig(
            colors=32,
            simplify=1.0,
            ordering="containment",
            underlap=1,
            curve_fit="cubic",
            curve_error=1.0,
            path_batching="consecutive",
            batch_safety_margin=margin,
        ),
        include_comparisons=False,
    )
    metrics = report["metrics"]
    metrics["total_runtime_ms"] = (perf_counter() - started) * 1000.0
    metrics["test_id"] = test_id
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return metrics


def _compare_to_baseline(output: Path, test_id: str, metrics: dict[float, dict]) -> list[dict]:
    baseline_dir = output / test_id / "margin_1p0"
    baseline_pixels = np.asarray(
        Image.open(baseline_dir / "rendered.png").convert("RGB"), dtype=np.uint8
    )
    baseline_geometry, _, baseline_styles = _svg_streams(baseline_dir / "output.svg")
    rows: list[dict] = []
    for margin in MARGINS:
        run_dir = output / test_id / f"margin_{_margin_name(margin)}"
        candidate = np.asarray(Image.open(run_dir / "rendered.png").convert("RGB"), dtype=np.uint8)
        delta = np.abs(candidate.astype(np.int16) - baseline_pixels.astype(np.int16))
        geometry, _, styles = _svg_streams(run_dir / "output.svg")
        changed = np.any(delta > 0, axis=2)
        flat_index = int(np.argmax(delta.max(axis=2)))
        y, x = np.unravel_index(flat_index, changed.shape)
        record = metrics[margin]
        rows.append(
            {
                "test_id": test_id,
                "margin": margin,
                "region_count": record["region_count"],
                "paths_before_batch": record["region_count"],
                "paths_after_batch": record["svg_element_count"],
                "path_reduction_ratio": 1.0 - record["svg_element_count"] / record["region_count"],
                "compound_path_count": record["compound_path_count"],
                "singleton_count": record["batch_size_distribution"]["1"],
                "maximum_batch_size": record["max_batch_size"],
                "svg_file_size_bytes": record["svg_file_size_bytes"],
                "rasterization_ms": record["svg_rasterization_ms"],
                "total_runtime_ms": record["total_runtime_ms"],
                "mean_absolute_render_delta_vs_1px": float(delta.mean()),
                "max_channel_delta_vs_1px": int(delta.max()),
                "changed_pixel_ratio_vs_1px": float(changed.mean()),
                "max_delta_x": int(x),
                "max_delta_y": int(y),
                "geometry_stream_identical_to_1px": geometry == baseline_geometry,
                "paint_style_stream_identical_to_1px": styles == baseline_styles,
            }
        )
    return rows


def _grid(output: Path) -> None:
    tile, label_height = 210, 22
    grid = Image.new("RGB", (tile * 6, (tile + label_height) * len(INPUTS)), "white")
    draw = ImageDraw.Draw(grid)
    for row, test_id in enumerate(INPUTS):
        baseline = np.asarray(
            Image.open(output / test_id / "margin_1p0" / "rendered.png").convert("RGB"),
            dtype=np.uint8,
        )
        zero = np.asarray(
            Image.open(output / test_id / "margin_0p0" / "rendered.png").convert("RGB"),
            dtype=np.uint8,
        )
        delta = np.abs(zero.astype(np.int16) - baseline.astype(np.int16))
        delta_path = output / test_id / "margin_0p0" / "delta_vs_1px_x32.png"
        Image.fromarray(np.clip(delta * 32, 0, 255).astype(np.uint8)).save(delta_path)
        panels = [
            ("source", output / test_id / "margin_1p0" / "source.png"),
            ("margin 0", output / test_id / "margin_0p0" / "rendered.png"),
            ("margin 0.5", output / test_id / "margin_0p5" / "rendered.png"),
            ("margin 1", output / test_id / "margin_1p0" / "rendered.png"),
            ("margin 2", output / test_id / "margin_2p0" / "rendered.png"),
            ("0 vs 1 delta x32", delta_path),
        ]
        for column, (label, path) in enumerate(panels):
            image = Image.open(path).convert("RGB")
            fitted = ImageOps.contain(image, (tile, tile), Image.Resampling.LANCZOS)
            x0, y0 = column * tile, row * (tile + label_height)
            grid.paste(
                fitted,
                (x0 + (tile - fitted.width) // 2, y0 + label_height + (tile - fitted.height) // 2),
            )
            draw.text((x0 + 4, y0 + 4), f"{test_id} {label}", fill="black")
    grid.save(output / "comparison_grid.png")


def run(output: Path) -> list[dict]:
    repo = Path(__file__).resolve().parents[1]
    output.mkdir(parents=True, exist_ok=True)
    all_metrics: dict[str, dict[float, dict]] = {}
    for test_id, input_path in INPUTS.items():
        all_metrics[test_id] = {
            margin: _run(repo, output, test_id, input_path, margin) for margin in MARGINS
        }
    rows = [
        row
        for test_id in INPUTS
        for row in _compare_to_baseline(output, test_id, all_metrics[test_id])
    ]
    with (output / "comparison.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output / "summary.json").write_text(
        json.dumps({"margins": list(MARGINS), "runs": rows}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _grid(output)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("out/phase5-margin"))
    args = parser.parse_args(argv)
    print(json.dumps(run(args.output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
