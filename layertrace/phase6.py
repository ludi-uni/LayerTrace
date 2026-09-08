"""Compare LayerTrace with the official VTracer stacked vectorizer."""

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

import cairosvg
import numpy as np
from PIL import Image, ImageDraw, ImageOps

from .core import extract_regions, merge_small_components, order_regions, quantize_image
from .phase3 import INPUTS
from .svg import write_svg


LAYERTRACE_SETTINGS = {
    "colors": 32,
    "simplify": 1.0,
    "ordering": "containment",
    "underlap": 1,
    "curve_fit": "off",
    "path_batching": "consecutive",
    "batch_safety_margin": 1.0,
}

VTRACER_SETTINGS = {
    "colormode": "color",
    "hierarchical": "stacked",
    "mode": "spline",
    "filter_speckle": 4,
    "color_precision": 6,
    "gradient_step": 16,
    "corner_threshold": 60,
    "segment_length": 4,
    "splice_threshold": 45,
    "path_precision": 2,
}


def _layertrace_vectorize(input_path: Path, output_path: Path) -> dict:
    source = Image.open(input_path).convert("RGB")
    labels, palette, _ = quantize_image(source, LAYERTRACE_SETTINGS["colors"], 0.0)
    labels = merge_small_components(labels, 4)
    palette = {int(label): palette[int(label)] for label in np.unique(labels)}
    regions = extract_regions(labels, palette, min_area=1)
    ordered = order_regions(regions, LAYERTRACE_SETTINGS["ordering"])
    stats = write_svg(
        output_path,
        source.width,
        source.height,
        ordered,
        underlap=LAYERTRACE_SETTINGS["underlap"],
        simplify=LAYERTRACE_SETTINGS["simplify"],
        curve_fit=LAYERTRACE_SETTINGS["curve_fit"],
        curve_error=1.0,
        path_batching=LAYERTRACE_SETTINGS["path_batching"],
        batch_safety_margin=LAYERTRACE_SETTINGS["batch_safety_margin"],
    )
    return {"region_count": len(regions), **stats}


def _vtracer_command(
    executable: Path, input_path: Path, output_path: Path, color_precision: int = 6
) -> list[str]:
    return [
        str(executable),
        "--input", str(input_path),
        "--output", str(output_path),
        "--colormode", "color",
        "--hierarchical", "stacked",
        "--mode", "spline",
        "--filter_speckle", "4",
        "--color_precision", str(color_precision),
        "--gradient_step", "16",
        "--corner_threshold", "60",
        "--segment_length", "4",
        "--splice_threshold", "45",
        "--path_precision", "2",
    ]


def _median_vectorization(
    method: str,
    executable: Path,
    input_path: Path,
    output_path: Path,
    vtracer_color_precision: int = 6,
) -> tuple[float, dict]:
    samples: list[float] = []
    stats: dict = {}
    for _ in range(3):
        started = perf_counter()
        if method == "layertrace":
            stats = _layertrace_vectorize(input_path, output_path)
        else:
            completed = subprocess.run(
                _vtracer_command(
                    executable, input_path, output_path, vtracer_color_precision
                ),
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr or completed.stdout)
        samples.append((perf_counter() - started) * 1000.0)
    return statistics.median(samples), {"samples_ms": samples, **stats}


def _render(svg_path: Path, png_path: Path, width: int, height: int) -> tuple[np.ndarray, float]:
    samples: list[float] = []
    rendered = np.empty((height, width, 3), dtype=np.uint8)
    for _ in range(3):
        started = perf_counter()
        png = cairosvg.svg2png(
            url=str(svg_path), output_width=width, output_height=height, background_color="#ffffff"
        )
        samples.append((perf_counter() - started) * 1000.0)
        from io import BytesIO

        rendered = np.asarray(Image.open(BytesIO(png)).convert("RGB"), dtype=np.uint8)
    Image.fromarray(rendered).save(png_path)
    return rendered, statistics.median(samples)


def _svg_structure(path: Path) -> dict[str, int | float | bool]:
    root = ET.parse(path).getroot()
    elements = list(root.iter())
    paths = [element for element in elements if element.tag.rsplit("}", 1)[-1] == "path"]
    polygons = [element for element in elements if element.tag.rsplit("}", 1)[-1] == "polygon"]
    groups = [element for element in elements if element.tag.rsplit("}", 1)[-1] == "g"]
    path_data = [element.attrib.get("d", "") for element in paths]
    command_count = sum(
        len(re.findall(r"[MmLlHhVvCcSsQqTtAaZz]", data)) for data in path_data
    )
    curve_count = sum(len(re.findall(r"[CcSsQqTtAa]", data)) for data in path_data)
    fills: set[str] = set()
    for element in elements:
        if "fill" in element.attrib:
            fills.add(element.attrib["fill"])
        style = element.attrib.get("style", "")
        match = re.search(r"(?:^|;)\s*fill\s*:\s*([^;]+)", style)
        if match:
            fills.add(match.group(1).strip())
    return {
        "svg_path_element_count": len(paths),
        "svg_polygon_element_count": len(polygons),
        "svg_group_element_count": len(groups),
        "total_path_commands": command_count,
        "curve_command_count": curve_count,
        "uses_curves": curve_count > 0,
        "distinct_explicit_fills": len(fills),
        "average_path_data_bytes": (
            sum(len(data.encode("utf-8")) for data in path_data) / len(path_data) if path_data else 0.0
        ),
        "svg_file_size_bytes": path.stat().st_size,
    }


def _image_metrics(source: np.ndarray, rendered: np.ndarray) -> dict[str, float | int]:
    delta = np.abs(source.astype(np.int16) - rendered.astype(np.int16))
    return {
        "mean_absolute_rgb_error": float(delta.mean()),
        "max_rgb_error": int(delta.max()),
        "different_pixel_ratio": float(np.any(delta > 0, axis=2).mean()),
    }


def _grid(output: Path) -> None:
    tile, label_height = 220, 22
    grid = Image.new("RGB", (tile * 5, (tile + label_height) * len(INPUTS)), "white")
    draw = ImageDraw.Draw(grid)
    for row, test_id in enumerate(INPUTS):
        directory = output / test_id
        panels = [
            ("source", directory / "source.png"),
            ("LayerTrace", directory / "layertrace_rendered.png"),
            ("VTracer", directory / "vtracer_rendered.png"),
            ("LT diff", directory / "layertrace_diff.png"),
            ("VT diff", directory / "vtracer_diff.png"),
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


def _palette_grid(output: Path) -> None:
    tile, label_height = 220, 22
    grid = Image.new("RGB", (tile * 4, (tile + label_height) * len(INPUTS)), "white")
    draw = ImageDraw.Draw(grid)
    for row, test_id in enumerate(INPUTS):
        directory = output / test_id
        panels = [
            ("source", directory / "source.png"),
            ("LayerTrace 32", directory / "layertrace_rendered.png"),
            ("VTracer default", directory / "vtracer_rendered.png"),
            ("VTracer precision 2", directory / "vtracer_32ish_rendered.png"),
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
    grid.save(output / "palette_comparison_grid.png")


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
        vt_svg = directory / "vtracer.svg"
        vt_32ish_svg = directory / "vtracer_32ish.svg"
        lt_runtime, lt_internal = _median_vectorization("layertrace", executable, input_path, lt_svg)
        vt_runtime, vt_internal = _median_vectorization("vtracer", executable, input_path, vt_svg)
        vt_32ish_runtime, vt_32ish_internal = _median_vectorization(
            "vtracer", executable, input_path, vt_32ish_svg, vtracer_color_precision=2
        )
        lt_rendered, lt_raster_ms = _render(
            lt_svg, directory / "layertrace_rendered.png", source_image.width, source_image.height
        )
        vt_rendered, vt_raster_ms = _render(
            vt_svg, directory / "vtracer_rendered.png", source_image.width, source_image.height
        )
        vt_32ish_rendered, vt_32ish_raster_ms = _render(
            vt_32ish_svg,
            directory / "vtracer_32ish_rendered.png",
            source_image.width,
            source_image.height,
        )
        lt_diff = np.abs(source.astype(np.int16) - lt_rendered.astype(np.int16)).astype(np.uint8)
        vt_diff = np.abs(source.astype(np.int16) - vt_rendered.astype(np.int16)).astype(np.uint8)
        vt_32ish_diff = np.abs(
            source.astype(np.int16) - vt_32ish_rendered.astype(np.int16)
        ).astype(np.uint8)
        Image.fromarray(lt_diff).save(directory / "layertrace_diff.png")
        Image.fromarray(vt_diff).save(directory / "vtracer_diff.png")
        Image.fromarray(vt_32ish_diff).save(directory / "vtracer_32ish_diff.png")
        lt = {
            "runtime_ms": lt_runtime,
            "rasterization_ms": lt_raster_ms,
            **_svg_structure(lt_svg),
            **_image_metrics(source, lt_rendered),
            **lt_internal,
        }
        vt = {
            "runtime_ms": vt_runtime,
            "rasterization_ms": vt_raster_ms,
            **_svg_structure(vt_svg),
            **_image_metrics(source, vt_rendered),
            **vt_internal,
        }
        vt_32ish = {
            "runtime_ms": vt_32ish_runtime,
            "rasterization_ms": vt_32ish_raster_ms,
            **_svg_structure(vt_32ish_svg),
            **_image_metrics(source, vt_32ish_rendered),
            **vt_32ish_internal,
        }
        metrics = {
            "test_id": test_id,
            "input_path": relative_input.as_posix(),
            "image_width": source_image.width,
            "image_height": source_image.height,
            "layertrace": lt,
            "vtracer": vt,
            "vtracer_32ish": vt_32ish,
        }
        (directory / "metrics.json").write_text(
            json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        details[test_id] = metrics
        rows.append(
            {
                "test_id": test_id,
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
    identity = {
        "repository": "https://github.com/visioncortex/vtracer",
        "release": "https://github.com/visioncortex/vtracer/releases/tag/0.6.4",
        "version": version,
        "license": "MIT OR Apache-2.0",
        "binary_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
    }
    summary = {
        "measurement": {
            "repetitions": 3,
            "statistic": "median",
            "vectorization_scope": "input load through SVG write; VTracer includes process startup",
            "rasterizer": "CairoSVG",
        },
        "layertrace_settings": LAYERTRACE_SETTINGS,
        "vtracer_settings": VTRACER_SETTINGS,
        "vtracer_32ish_settings": {**VTRACER_SETTINGS, "color_precision": 2},
        "vtracer_identity": identity,
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
    _palette_grid(output)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vtracer", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("out/phase6-vtracer-comparison"))
    args = parser.parse_args(argv)
    print(json.dumps(run(args.output, args.vtracer.resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
