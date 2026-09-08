"""Benchmark the current line baseline against optional cubic representation."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from time import perf_counter

from PIL import Image, ImageDraw, ImageOps

from .pipeline import TraceConfig, trace_image


INPUTS = {
    "test_1": Path("examples/test_pic/test1.png"),
    "test_2": Path("examples/test_pic/test2.png"),
    "test_3": Path("examples/test_pic/test3.png"),
    "test_4": Path("examples/test_pic/test4.png"),
    "test_5": Path("examples/test_pic/test5.png"),
}


def _trace_record(
    repo: Path,
    root: Path,
    group: str,
    test_id: str,
    input_path: Path,
    curve_fit: str,
) -> dict:
    run_dir = root / group / test_id
    started = perf_counter()
    report = trace_image(
        repo / input_path,
        run_dir,
        TraceConfig(
            colors=32,
            simplify=1.0,
            ordering="containment",
            underlap=1,
            curve_fit=curve_fit,
            curve_error=1.0,
        ),
        include_comparisons=False,
    )
    metrics = report["metrics"]
    metrics["runtime_ms"] = (perf_counter() - started) * 1000.0
    metrics["test_id"] = test_id
    metrics["curve_fit"] = curve_fit
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return metrics


def _comparison_row(baseline: dict, optimized: dict) -> dict:
    return {
        "test_id": baseline["test_id"],
        "runtime_before_ms": baseline["runtime_ms"],
        "runtime_after_ms": optimized["runtime_ms"],
        "runtime_change_percent": (optimized["runtime_ms"] / baseline["runtime_ms"] - 1.0) * 100.0,
        "svg_before_bytes": baseline["svg_file_size_bytes"],
        "svg_after_bytes": optimized["svg_file_size_bytes"],
        "svg_change_percent": (
            optimized["svg_file_size_bytes"] / baseline["svg_file_size_bytes"] - 1.0
        )
        * 100.0,
        "commands_before": baseline["total_path_commands"],
        "commands_after": optimized["total_path_commands"],
        "commands_change_percent": (
            optimized["total_path_commands"] / baseline["total_path_commands"] - 1.0
        )
        * 100.0,
        "line_commands_before": baseline["line_command_count"],
        "line_commands_after": optimized["line_command_count"],
        "cubic_commands_after": optimized["cubic_command_count"],
        "mae_before": baseline["mean_absolute_rgb_error"],
        "mae_after": optimized["mean_absolute_rgb_error"],
        "mae_change_percent": (
            optimized["mean_absolute_rgb_error"] / baseline["mean_absolute_rgb_error"] - 1.0
        )
        * 100.0,
        "different_pixel_ratio_before": baseline["different_pixel_ratio"],
        "different_pixel_ratio_after": optimized["different_pixel_ratio"],
        "white_gaps_before": baseline["white_gap_pixel_count"],
        "white_gaps_after": optimized["white_gap_pixel_count"],
        "shapes_before": baseline["svg_shape_count"],
        "shapes_after": optimized["svg_shape_count"],
        "vertices_before": baseline["total_vertices"],
        "vertices_after": optimized["total_vertices"],
    }


def _comparison_grid(root: Path) -> None:
    tile_width, tile_height, label_height = 220, 294, 22
    grid = Image.new(
        "RGB", (tile_width * 5, (tile_height + label_height) * len(INPUTS)), "white"
    )
    draw = ImageDraw.Draw(grid)
    for row, test_id in enumerate(INPUTS):
        baseline = root / "baseline" / test_id
        optimized = root / "optimized" / test_id
        panels = [
            ("source", baseline / "source.png"),
            ("baseline", baseline / "rendered.png"),
            ("optimized", optimized / "rendered.png"),
            ("baseline diff", baseline / "diff.png"),
            ("optimized diff", optimized / "diff.png"),
        ]
        for column, (label, path) in enumerate(panels):
            image = Image.open(path).convert("RGB")
            fitted = ImageOps.contain(image, (tile_width, tile_height), Image.Resampling.LANCZOS)
            x = column * tile_width + (tile_width - fitted.width) // 2
            y0 = row * (tile_height + label_height)
            y = y0 + label_height + (tile_height - fitted.height) // 2
            grid.paste(fitted, (x, y))
            draw.text((column * tile_width + 4, y0 + 4), f"{test_id} {label}", fill="black")
    grid.save(root / "comparison_grid.png")


def run(root: Path) -> list[dict]:
    repo = Path(__file__).resolve().parents[1]
    root.mkdir(parents=True, exist_ok=True)
    baselines = [
        _trace_record(repo, root, "baseline", test_id, input_path, "off")
        for test_id, input_path in INPUTS.items()
    ]
    optimized = [
        _trace_record(repo, root, "optimized", test_id, input_path, "cubic")
        for test_id, input_path in INPUTS.items()
    ]
    comparisons = [_comparison_row(before, after) for before, after in zip(baselines, optimized)]
    (root / "baseline_summary.json").write_text(
        json.dumps({"runs": baselines}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (root / "optimized_summary.json").write_text(
        json.dumps({"runs": optimized}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with (root / "comparison.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(comparisons[0]))
        writer.writeheader()
        writer.writerows(comparisons)
    _comparison_grid(root)
    return comparisons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("out/phase3-efficiency"))
    args = parser.parse_args(argv)
    comparisons = run(args.output)
    print(json.dumps(comparisons, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
