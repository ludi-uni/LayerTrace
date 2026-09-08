"""Benchmark paint-equivalent consecutive path batching."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from time import perf_counter
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from .phase3 import INPUTS
from .pipeline import TraceConfig, trace_image


def _config(path_batching: str) -> TraceConfig:
    return TraceConfig(
        colors=32,
        simplify=1.0,
        ordering="containment",
        underlap=1,
        curve_fit="cubic",
        curve_error=1.0,
        path_batching=path_batching,
    )


def _run(repo: Path, output: Path, test_id: str, input_path: Path, mode: str) -> dict:
    run_dir = output / mode / test_id
    started = perf_counter()
    report = trace_image(
        repo / input_path,
        run_dir,
        _config("off" if mode == "baseline" else "consecutive"),
        include_comparisons=False,
    )
    metrics = report["metrics"]
    metrics["total_runtime_ms"] = (perf_counter() - started) * 1000.0
    metrics["test_id"] = test_id
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return metrics


def _svg_streams(path: Path) -> tuple[str, list[str], list[tuple[str, str, str, str, str]]]:
    root = ET.parse(path).getroot()
    elements = root.findall("{http://www.w3.org/2000/svg}path")
    geometry = " ".join(element.attrib["d"] for element in elements)
    fills: list[str] = []
    styles: list[tuple[str, str, str, str, str]] = []
    for element in elements:
        count = int(element.attrib.get("data-region-count", "1"))
        style = (
            element.attrib["fill"],
            element.attrib.get("stroke", "none"),
            element.attrib.get("opacity", "1"),
            element.attrib.get("fill-rule", "nonzero"),
            element.attrib.get("transform", "none"),
        )
        fills.extend([element.attrib["fill"]] * count)
        styles.extend([style] * count)
    return geometry, fills, styles


def _compare(output: Path, test_id: str, baseline: dict, batched: dict) -> dict:
    baseline_dir = output / "baseline" / test_id
    batched_dir = output / "batched" / test_id
    before = np.asarray(Image.open(baseline_dir / "rendered.png").convert("RGB"), dtype=np.uint8)
    after = np.asarray(Image.open(batched_dir / "rendered.png").convert("RGB"), dtype=np.uint8)
    delta = np.abs(before.astype(np.int16) - after.astype(np.int16))
    Image.fromarray(delta.astype(np.uint8)).save(batched_dir / "render_diff.png")
    Image.fromarray(np.clip(delta * 32, 0, 255).astype(np.uint8)).save(
        batched_dir / "render_diff_x32.png"
    )
    baseline_geometry, baseline_fills, baseline_styles = _svg_streams(baseline_dir / "output.svg")
    batched_geometry, batched_fills, batched_styles = _svg_streams(batched_dir / "output.svg")
    return {
        "test_id": test_id,
        "region_count": baseline["region_count"],
        "paths_before": baseline["svg_element_count"],
        "paths_after": batched["svg_element_count"],
        "path_reduction_percent": (
            1.0 - batched["svg_element_count"] / baseline["svg_element_count"]
        )
        * 100.0,
        "compound_path_count": batched["compound_path_count"],
        "subpath_count": batched["subpath_count"],
        "svg_before_bytes": baseline["svg_file_size_bytes"],
        "svg_after_bytes": batched["svg_file_size_bytes"],
        "file_reduction_percent": (
            1.0 - batched["svg_file_size_bytes"] / baseline["svg_file_size_bytes"]
        )
        * 100.0,
        "rasterize_before_ms": baseline["svg_rasterization_ms"],
        "rasterize_after_ms": batched["svg_rasterization_ms"],
        "rasterize_improvement_percent": (
            1.0 - batched["svg_rasterization_ms"] / baseline["svg_rasterization_ms"]
        )
        * 100.0,
        "total_runtime_before_ms": baseline["total_runtime_ms"],
        "total_runtime_after_ms": batched["total_runtime_ms"],
        "total_runtime_improvement_percent": (
            1.0 - batched["total_runtime_ms"] / baseline["total_runtime_ms"]
        )
        * 100.0,
        "total_path_commands": baseline["total_path_commands"],
        "commands_unchanged": baseline["total_path_commands"] == batched["total_path_commands"],
        "mae_before": baseline["mean_absolute_rgb_error"],
        "mae_after": batched["mean_absolute_rgb_error"],
        "different_pixel_ratio_before": baseline["different_pixel_ratio"],
        "different_pixel_ratio_after": batched["different_pixel_ratio"],
        "white_gaps_before": baseline["white_gap_pixel_count"],
        "white_gaps_after": batched["white_gap_pixel_count"],
        "render_different_pixels": int(np.any(delta > 0, axis=2).sum()),
        "render_different_pixel_ratio": float(np.any(delta > 0, axis=2).mean()),
        "render_max_channel_delta": int(delta.max()),
        "render_mean_absolute_delta": float(delta.mean()),
        "geometry_stream_identical": baseline_geometry == batched_geometry,
        "geometry_stream_sha256": hashlib.sha256(baseline_geometry.encode()).hexdigest(),
        "paint_fill_stream_identical": baseline_fills == batched_fills,
        "paint_style_stream_identical": baseline_styles == batched_styles,
    }


def _grid(output: Path) -> None:
    tile_width, tile_height, label_height = 190, 260, 22
    columns = 6
    grid = Image.new("RGB", (tile_width * columns, (tile_height + label_height) * len(INPUTS)), "white")
    draw = ImageDraw.Draw(grid)
    for row, test_id in enumerate(INPUTS):
        baseline = output / "baseline" / test_id
        batched = output / "batched" / test_id
        panels = [
            ("source", baseline / "source.png"),
            ("baseline", baseline / "rendered.png"),
            ("batched", batched / "rendered.png"),
            ("render Δ×32", batched / "render_diff_x32.png"),
            ("baseline diff", baseline / "diff.png"),
            ("batched diff", batched / "diff.png"),
        ]
        for column, (label, path) in enumerate(panels):
            image = Image.open(path).convert("RGB")
            fitted = ImageOps.contain(image, (tile_width, tile_height), Image.Resampling.LANCZOS)
            x0 = column * tile_width
            y0 = row * (tile_height + label_height)
            grid.paste(
                fitted,
                (x0 + (tile_width - fitted.width) // 2, y0 + label_height + (tile_height - fitted.height) // 2),
            )
            draw.text((x0 + 4, y0 + 4), f"{test_id} {label}", fill="black")
    grid.save(output / "comparison_grid.png")


def run(output: Path) -> list[dict]:
    repo = Path(__file__).resolve().parents[1]
    output.mkdir(parents=True, exist_ok=True)
    baseline: list[dict] = []
    batched: list[dict] = []
    comparisons: list[dict] = []
    for test_id, input_path in INPUTS.items():
        before = _run(repo, output, test_id, input_path, "baseline")
        after = _run(repo, output, test_id, input_path, "batched")
        if before["region_count"] != after["region_count"]:
            raise RuntimeError(f"region count changed for {test_id}")
        baseline.append(before)
        batched.append(after)
        comparisons.append(_compare(output, test_id, before, after))
    (output / "baseline_summary.json").write_text(
        json.dumps({"runs": baseline}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output / "batched_summary.json").write_text(
        json.dumps({"runs": batched}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output / "batch_distribution.json").write_text(
        json.dumps(
            {record["test_id"]: record["batch_size_distribution"] for record in batched},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    with (output / "comparison.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(comparisons[0]))
        writer.writeheader()
        writer.writerows(comparisons)
    _grid(output)
    return comparisons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("out/phase4-batching"))
    args = parser.parse_args(argv)
    print(json.dumps(run(args.output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
