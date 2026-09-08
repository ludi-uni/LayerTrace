from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from time import perf_counter

import cairosvg
import cv2
import numpy as np
from PIL import Image

from .core import extract_regions, labels_to_rgb, merge_small_components, order_regions, quantize_image
from .svg import write_svg


@dataclass(frozen=True)
class TraceConfig:
    colors: int = 32
    underlap: int = 2
    simplify: float = 1.0
    min_area: int = 4
    smoothing: float = 0.0
    ordering: str = "containment"
    curve_fit: str = "off"
    curve_error: float = 1.0
    path_batching: str = "off"
    batch_safety_margin: float = 1.0


def _render_svg(
    svg_path: Path, png_path: Path, width: int, height: int
) -> tuple[np.ndarray, np.ndarray]:
    cairosvg.svg2png(
        url=str(svg_path),
        write_to=str(png_path),
        output_width=width,
        output_height=height,
    )
    rgba = np.asarray(Image.open(png_path).convert("RGBA"), dtype=np.uint8)
    alpha = rgba[:, :, 3]
    weight = alpha.astype(np.float32)[:, :, None] / 255.0
    composited = np.rint(rgba[:, :, :3] * weight + 255.0 * (1.0 - weight)).astype(np.uint8)
    Image.fromarray(composited).save(png_path)
    return composited, alpha


def _metrics(
    source: np.ndarray,
    rendered: np.ndarray,
    labels: np.ndarray,
    alpha: np.ndarray,
    background_label: int,
    color_count: int,
    region_count: int,
    svg_stats: dict[str, object],
) -> dict[str, object]:
    delta = np.abs(source.astype(np.int16) - rendered.astype(np.int16))
    different = np.any(delta > 0, axis=2)
    # Alpha distinguishes exposed white canvas from legitimate white foreground.
    white_gap = (labels != background_label) & (alpha < 250)
    return {
        "input_width": int(source.shape[1]),
        "input_height": int(source.shape[0]),
        "quantized_colors": int(color_count),
        "region_count": int(region_count),
        **svg_stats,
        "mean_absolute_rgb_error": float(delta.mean()),
        "max_rgb_error": int(delta.max()),
        "different_pixel_ratio": float(different.mean()),
        "white_gap_pixel_count": int(white_gap.sum()),
    }


def _write_variant(
    output_dir: Path,
    source: np.ndarray,
    labels: np.ndarray,
    palette: dict[int, tuple[int, int, int]],
    regions,
    ordered,
    underlap: int,
    simplify: float,
    curve_fit: str,
    curve_error: float,
    path_batching: str,
    batch_safety_margin: float,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    height, width = labels.shape
    svg_path = output_dir / "output.svg"
    variant_started = perf_counter()
    generation_started = perf_counter()
    svg_stats = write_svg(
        svg_path,
        width,
        height,
        ordered,
        underlap=underlap,
        simplify=simplify,
        curve_fit=curve_fit,
        curve_error=curve_error,
        path_batching=path_batching,
        batch_safety_margin=batch_safety_margin,
    )
    svg_generation_ms = (perf_counter() - generation_started) * 1000.0
    raster_started = perf_counter()
    rendered, alpha = _render_svg(svg_path, output_dir / "rendered.png", width, height)
    svg_rasterization_ms = (perf_counter() - raster_started) * 1000.0
    metrics_started = perf_counter()
    diff = np.abs(source.astype(np.int16) - rendered.astype(np.int16)).astype(np.uint8)
    Image.fromarray(diff).save(output_dir / "diff.png")
    values, counts = np.unique(labels, return_counts=True)
    background_label = int(values[np.argmax(counts)])
    metrics = _metrics(
        source,
        rendered,
        labels,
        alpha,
        background_label,
        len(palette),
        len(regions),
        svg_stats,
    )
    metrics["underlap"] = int(underlap)
    metrics["svg_file_size_bytes"] = svg_path.stat().st_size
    metrics["svg_generation_ms"] = svg_generation_ms
    metrics["svg_rasterization_ms"] = svg_rasterization_ms
    metrics["diff_metrics_ms"] = (perf_counter() - metrics_started) * 1000.0
    metrics["variant_runtime_ms"] = (perf_counter() - variant_started) * 1000.0
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return metrics


def trace_image(
    input_path: str | Path,
    output_dir: str | Path,
    config: TraceConfig,
    *,
    include_comparisons: bool = True,
) -> dict:
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_image = Image.open(input_path).convert("RGB")
    source = np.asarray(source_image, dtype=np.uint8)
    labels, palette, _ = quantize_image(source_image, config.colors, config.smoothing)
    labels = merge_small_components(labels, config.min_area)
    palette = {int(label): palette[int(label)] for label in np.unique(labels)}
    quantized_array = labels_to_rgb(labels, palette)
    quantized_image = Image.fromarray(quantized_array)
    regions = extract_regions(labels, palette, min_area=1)
    ordered = order_regions(regions, config.ordering)

    source_image.save(output_dir / "source.png")
    quantized_image.save(output_dir / "quantized.png")
    region_preview = quantized_array.copy()
    for region in regions:
        cv2.drawContours(region_preview, region.contours, -1, (0, 0, 0), 1)
    Image.fromarray(region_preview).save(output_dir / "regions.png")

    primary_metrics = _write_variant(
        output_dir,
        source,
        labels,
        palette,
        regions,
        ordered,
        config.underlap,
        config.simplify,
        config.curve_fit,
        config.curve_error,
        config.path_batching,
        config.batch_safety_margin,
    )
    comparison_root = output_dir / "comparisons"
    positive = config.underlap if config.underlap > 0 else 2
    comparisons: dict[str, dict[str, int | float]] = {}
    if include_comparisons:
        for amount in sorted({0, positive}):
            key = f"underlap_{amount}"
            comparisons[key] = _write_variant(
                comparison_root / key,
                source,
                labels,
                palette,
                regions,
                ordered,
                amount,
                config.simplify,
                config.curve_fit,
                config.curve_error,
                config.path_batching,
                config.batch_safety_margin,
            )
    manifest = {
        "config": asdict(config),
        "layer_order": [region.id for region in ordered],
        "regions": [
            {
                "id": region.id,
                "color": list(region.color),
                "area": region.area,
                "bbox": list(region.bbox),
                "centroid": list(region.centroid),
                "parent_id": region.parent_id,
                "containment_depth": region.containment_depth,
            }
            for region in regions
        ],
        "metrics": primary_metrics,
        "comparisons": comparisons,
    }
    (output_dir / "run.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest
