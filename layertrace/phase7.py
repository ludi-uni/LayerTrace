"""Compare LayerTrace and VTracer 1.0 at strict 32-color parity."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import statistics
import subprocess
from time import perf_counter
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from .phase3 import INPUTS
from .phase6 import (
    LAYERTRACE_SETTINGS,
    _image_metrics,
    _layertrace_vectorize,
    _render,
    _svg_structure,
)


VTRACER_SETTINGS = {
    "clustering": "color-cluster",
    "hierarchical": "stacked",
    "mode": "spline",
    "filter_speckle": 4,
    "color_precision": 6,
    "gradient_step": 16,
    "path_precision": 2,
    "max_colors": 32,
    "optimize": 1,
}


def _vtracer_command(executable: Path, input_path: Path, output_path: Path) -> list[str]:
    return [
        str(executable),
        str(input_path),
        str(output_path),
        "--clustering", "color-cluster",
        "--hierarchical", "stacked",
        "--mode", "spline",
        "--filter-speckle", "4",
        "--color-precision", "6",
        "--gradient-step", "16",
        "--path-precision", "2",
        "--max-colors", "32",
        "--optimize", "1",
    ]


def _median_layertrace(input_path: Path, output_path: Path) -> tuple[float, dict]:
    samples: list[float] = []
    stats: dict = {}
    for _ in range(3):
        started = perf_counter()
        stats = _layertrace_vectorize(input_path, output_path)
        samples.append((perf_counter() - started) * 1000.0)
    return statistics.median(samples), {"samples_ms": samples, **stats}


def _median_vtracer(
    executable: Path, input_path: Path, output_path: Path
) -> tuple[float, dict]:
    samples: list[float] = []
    for _ in range(3):
        started = perf_counter()
        completed = subprocess.run(
            _vtracer_command(executable, input_path, output_path),
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr or completed.stdout)
        samples.append((perf_counter() - started) * 1000.0)
    return statistics.median(samples), {"samples_ms": samples}


def _fill_colors(path: Path) -> set[str]:
    root = ET.parse(path).getroot()
    fills: set[str] = set()
    for element in root.iter():
        fill = element.attrib.get("fill")
        if fill and fill.strip().lower() not in {"none", "transparent"}:
            fills.add(fill.strip().lower())
        style = element.attrib.get("style", "")
        match = re.search(r"(?:^|;)\s*fill\s*:\s*([^;]+)", style)
        if match and match.group(1).strip().lower() not in {"none", "transparent"}:
            fills.add(match.group(1).strip().lower())
    return fills


def _structure(path: Path) -> dict:
    metrics = _svg_structure(path)
    root = ET.parse(path).getroot()
    data = " ".join(
        element.attrib.get("d", "")
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "path"
    )
    metrics["line_command_count"] = len(re.findall(r"[LlHhVv]", data))
    metrics["cubic_command_count"] = len(re.findall(r"[CcSs]", data))
    metrics["actual_distinct_fill_colors"] = len(_fill_colors(path))
    metrics["requested_max_colors"] = 32
    return metrics


def _grid(output: Path) -> None:
    tile, label_height = 220, 22
    grid = Image.new("RGB", (tile * 5, (tile + label_height) * len(INPUTS)), "white")
    draw = ImageDraw.Draw(grid)
    for row, test_id in enumerate(INPUTS):
        directory = output / test_id
        panels = [
            ("source", directory / "source.png"),
            ("LayerTrace 32", directory / "layertrace_rendered.png"),
            ("VTracer 32", directory / "vtracer32_rendered.png"),
            ("LT diff", directory / "layertrace_diff.png"),
            ("VT diff", directory / "vtracer32_diff.png"),
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


def run(output: Path, executable: Path) -> list[dict]:
    repo = Path(__file__).resolve().parents[1]
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    details: dict[str, dict] = {}
    for test_id, relative_input in INPUTS.items():
        input_path = repo / relative_input
        directory = output / test_id
        directory.mkdir(parents=True, exist_ok=True)
        source_image = Image.open(input_path).convert("RGB")
        source_image.save(directory / "source.png")
        source = np.asarray(source_image, dtype=np.uint8)
        lt_svg = directory / "layertrace.svg"
        vt_svg = directory / "vtracer32.svg"
        lt_runtime, lt_internal = _median_layertrace(input_path, lt_svg)
        vt_runtime, vt_internal = _median_vtracer(executable, input_path, vt_svg)
        lt_rendered, lt_raster = _render(
            lt_svg, directory / "layertrace_rendered.png", source_image.width, source_image.height
        )
        vt_rendered, vt_raster = _render(
            vt_svg, directory / "vtracer32_rendered.png", source_image.width, source_image.height
        )
        lt_delta = np.abs(source.astype(np.int16) - lt_rendered.astype(np.int16)).astype(np.uint8)
        vt_delta = np.abs(source.astype(np.int16) - vt_rendered.astype(np.int16)).astype(np.uint8)
        Image.fromarray(lt_delta).save(directory / "layertrace_diff.png")
        Image.fromarray(vt_delta).save(directory / "vtracer32_diff.png")
        lt = {
            "runtime_ms": lt_runtime,
            "rasterization_ms": lt_raster,
            **_structure(lt_svg),
            **_image_metrics(source, lt_rendered),
            **lt_internal,
        }
        vt = {
            "runtime_ms": vt_runtime,
            "rasterization_ms": vt_raster,
            **_structure(vt_svg),
            **_image_metrics(source, vt_rendered),
            **vt_internal,
        }
        metrics = {
            "test_id": test_id,
            "input_path": relative_input.as_posix(),
            "image_width": source_image.width,
            "image_height": source_image.height,
            "layertrace": lt,
            "vtracer32": vt,
        }
        (directory / "metrics.json").write_text(
            json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        details[test_id] = metrics
        rows.append(
            {
                "test_id": test_id,
                "lt_fills": lt["actual_distinct_fill_colors"],
                "vt_fills": vt["actual_distinct_fill_colors"],
                "lt_mae": lt["mean_absolute_rgb_error"],
                "vt_mae": vt["mean_absolute_rgb_error"],
                "lt_svg_bytes": lt["svg_file_size_bytes"],
                "vt_svg_bytes": vt["svg_file_size_bytes"],
                "lt_paths": lt["svg_path_element_count"],
                "vt_paths": vt["svg_path_element_count"],
                "lt_commands": lt["total_path_commands"],
                "vt_commands": vt["total_path_commands"],
                "lt_runtime_ms": lt_runtime,
                "vt_runtime_ms": vt_runtime,
            }
        )
    version = subprocess.run(
        [str(executable), "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    summary = {
        "measurement": {
            "repetitions": 3,
            "statistic": "median",
            "vectorization_scope": "input load through SVG write; VTracer includes process startup",
            "rasterizer": "CairoSVG",
        },
        "layertrace_settings": {**LAYERTRACE_SETTINGS, "requested_colors": 32},
        "vtracer_settings": VTRACER_SETTINGS,
        "vtracer_identity": {
            "repository": "https://github.com/visioncortex/vtracer",
            "release": "https://github.com/visioncortex/vtracer/releases/tag/1.0.0-alpha.4",
            "version": version,
            "license": "MIT OR Apache-2.0",
            "release_asset_sha256": "8eadb5529864265f003f791ad9cb128e1b9b8b8af8c21016f38b04706bcf3531",
            "binary_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        },
        "tests": details,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with (output / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _grid(output)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vtracer", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("out/phase7-32color-parity"))
    args = parser.parse_args(argv)
    print(json.dumps(run(args.output, args.vtracer.resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
