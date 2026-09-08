from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import cv2
from PIL import Image, ImageDraw

from layertrace.core import extract_regions, labels_to_rgb, merge_small_components, order_regions, quantize_image
from layertrace.curves import contour_path
from layertrace.evaluate import evaluation_matrix
from layertrace.pipeline import TraceConfig, trace_image


def _save(tmp_path: Path, name: str, draw_fn, size=(64, 64)) -> Path:
    image = Image.new("RGB", size, "white")
    draw_fn(ImageDraw.Draw(image))
    path = tmp_path / name
    image.save(path)
    return path


def test_simple_rectangle_regions(tmp_path: Path):
    source = _save(
        tmp_path,
        "rectangles.png",
        lambda d: (d.rectangle((4, 4, 30, 58), fill="#3366aa"), d.rectangle((31, 4, 59, 58), fill="#dd6644")),
    )
    labels, palette, _ = quantize_image(Image.open(source), colors=3, smoothing=0)
    regions = extract_regions(labels, palette, min_area=1)
    assert len(regions) == 3
    assert sorted(region.area for region in regions)[-2:] == [1485, 1595]


def test_nested_region_is_painted_in_front(tmp_path: Path):
    source = _save(
        tmp_path,
        "nested.png",
        lambda d: (d.rectangle((6, 6, 57, 57), fill="#225588"), d.ellipse((20, 20, 43, 43), fill="#ffcc33")),
    )
    labels, palette, _ = quantize_image(Image.open(source), colors=3, smoothing=0)
    regions = extract_regions(labels, palette, min_area=1)
    ordered = order_regions(regions, mode="containment")
    yellow = max(regions, key=lambda r: r.color[0] + r.color[1] - r.color[2])
    blue = max(regions, key=lambda r: r.color[2] - r.color[0])
    assert ordered.index(blue) < ordered.index(yellow)
    assert yellow.containment_depth > blue.containment_depth


def test_touching_regions_and_small_detail_survive(tmp_path: Path):
    source = _save(
        tmp_path,
        "detail.png",
        lambda d: (d.rectangle((4, 4, 32, 59), fill="#222222"), d.rectangle((33, 4, 59, 59), fill="#cc4444"), d.rectangle((44, 28, 46, 30), fill="#ffff44")),
    )
    labels, palette, _ = quantize_image(Image.open(source), colors=4, smoothing=0)
    regions = extract_regions(labels, palette, min_area=1)
    assert any(region.area == 9 for region in regions)
    assert len(regions) == 4


def test_underlap_reduces_background_exposure_and_svg_is_valid(tmp_path: Path):
    source = _save(
        tmp_path,
        "curves.png",
        lambda d: (d.ellipse((7, 5, 57, 60), fill="#315d9a"), d.polygon([(16, 48), (31, 13), (50, 49)], fill="#e8a438")),
    )
    out = tmp_path / "out"
    report = trace_image(
        source,
        out,
        TraceConfig(colors=3, underlap=2, simplify=3.0, min_area=1, smoothing=0),
    )
    zero = report["comparisons"]["underlap_0"]
    positive = report["comparisons"]["underlap_2"]
    assert zero["svg_shape_count"] == positive["svg_shape_count"] == zero["region_count"]
    assert positive["white_gap_pixel_count"] <= zero["white_gap_pixel_count"]
    assert positive["white_gap_pixel_count"] < zero["white_gap_pixel_count"] or positive["mean_absolute_rgb_error"] < zero["mean_absolute_rgb_error"]
    root = ET.parse(out / "output.svg").getroot()
    paths = root.findall("{http://www.w3.org/2000/svg}path")
    assert len(paths) == report["metrics"]["svg_shape_count"]
    assert all(path.attrib["id"].startswith("region-") for path in paths)
    assert all(path.attrib.get("stroke") == "none" for path in paths)


def test_jpeg_input_writes_required_outputs(tmp_path: Path):
    source = _save(
        tmp_path,
        "source.jpg",
        lambda d: d.rectangle((8, 8, 55, 55), fill="#5a76bb"),
    )
    output = tmp_path / "jpeg-out"
    trace_image(source, output, TraceConfig(colors=4, underlap=1, simplify=1.0))
    required = {
        "source.png",
        "quantized.png",
        "regions.png",
        "output.svg",
        "rendered.png",
        "diff.png",
        "metrics.json",
        "run.json",
    }
    assert required <= {path.name for path in output.iterdir()}


def test_evaluation_matrix_and_single_run_mode(tmp_path: Path):
    assert evaluation_matrix() == [
        ("area", 0),
        ("area", 1),
        ("area", 2),
        ("area", 4),
        ("containment", 0),
        ("containment", 1),
        ("containment", 2),
        ("containment", 4),
    ]
    source = _save(
        tmp_path,
        "single.png",
        lambda d: d.ellipse((8, 8, 55, 55), fill="#5a76bb"),
    )
    output = tmp_path / "single-run"
    report = trace_image(
        source,
        output,
        TraceConfig(colors=4, underlap=1, simplify=1.0),
        include_comparisons=False,
    )
    assert report["comparisons"] == {}
    assert not (output / "comparisons").exists()


def test_small_component_merge_dilates_only_local_windows(monkeypatch):
    labels = np.zeros((64, 64), dtype=np.int32)
    labels[10, 10] = 1
    labels[30, 30] = 1
    labels[50, 50] = 1
    original = cv2.dilate
    seen_shapes = []

    def recording_dilate(source, *args, **kwargs):
        seen_shapes.append(source.shape)
        return original(source, *args, **kwargs)

    monkeypatch.setattr(cv2, "dilate", recording_dilate)
    merged = merge_small_components(labels, min_area=2)
    assert np.all(merged == 0)
    assert seen_shapes
    assert max(height * width for height, width in seen_shapes) <= 9


def test_regions_store_bbox_local_masks():
    labels = np.zeros((64, 64), dtype=np.int32)
    labels[20:23, 30:34] = 1
    regions = extract_regions(labels, {0: (255, 255, 255), 1: (0, 0, 0)}, min_area=1)
    detail = next(region for region in regions if region.label == 1)
    assert detail.bbox == (30, 20, 4, 3)
    assert detail.mask.shape == (3, 4)


def test_containment_prunes_spatially_impossible_candidates(monkeypatch):
    labels = np.zeros((256, 256), dtype=np.int32)
    palette = {0: (255, 255, 255)}
    label = 1
    for row in range(5):
        for column in range(6):
            size = 2 + ((row * 6 + column) % 8)
            y, x = 10 + row * 45, 10 + column * 40
            labels[y : y + size, x : x + size] = label
            palette[label] = (label, label, label)
            label += 1
    original = cv2.pointPolygonTest
    calls = 0

    def recording_test(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(cv2, "pointPolygonTest", recording_test)
    regions = extract_regions(labels, palette, min_area=1)
    assert len(regions) == 31
    assert calls < 100


def test_cubic_curve_reduces_smooth_contour_commands_but_keeps_corners_as_lines():
    angles = np.linspace(0, 2 * np.pi, 256, endpoint=False)
    circle = np.column_stack((50 + 30 * np.cos(angles), 50 + 30 * np.sin(angles)))
    line_path, line_stats = contour_path(circle, curve_fit="off", curve_error=1.0)
    cubic_path, cubic_stats = contour_path(circle, curve_fit="cubic", curve_error=1.0)
    assert "C" not in line_path
    assert cubic_stats.cubic_commands > 0
    assert cubic_stats.total_commands < line_stats.total_commands

    square = np.asarray([(0, 0), (20, 0), (20, 20), (0, 20)], dtype=float)
    square_path, square_stats = contour_path(square, curve_fit="cubic", curve_error=1.0)
    assert "C" not in square_path
    assert square_stats.line_commands == 3


def test_curve_metrics_and_visual_error_are_bounded(tmp_path: Path):
    source = _save(
        tmp_path,
        "circle.png",
        lambda d: d.ellipse((20, 20, 1003, 1003), fill="#315d9a"),
        size=(1024, 1024),
    )
    baseline = trace_image(
        source,
        tmp_path / "line",
        TraceConfig(colors=2, underlap=1, simplify=0.5, min_area=1, curve_fit="off"),
        include_comparisons=False,
    )["metrics"]
    optimized = trace_image(
        source,
        tmp_path / "cubic",
        TraceConfig(
            colors=2,
            underlap=1,
            simplify=0.5,
            min_area=1,
            curve_fit="cubic",
            curve_error=1.0,
        ),
        include_comparisons=False,
    )["metrics"]
    assert optimized["cubic_command_count"] > 0
    assert optimized["total_path_commands"] < baseline["total_path_commands"]
    assert optimized["svg_file_size_bytes"] < baseline["svg_file_size_bytes"]
    assert optimized["mean_absolute_rgb_error"] <= baseline["mean_absolute_rgb_error"] * 1.15


def test_palette_expansion_uses_one_indexed_lookup():
    labels = np.asarray([[0, 2], [2, 0]], dtype=np.int32)
    rgb = labels_to_rgb(labels, {0: (10, 20, 30), 2: (200, 210, 220)})
    assert rgb.tolist() == [
        [[10, 20, 30], [200, 210, 220]],
        [[200, 210, 220], [10, 20, 30]],
    ]


def test_consecutive_same_style_batching_is_pixel_identical(tmp_path: Path):
    def draw_details(draw):
        for x in (6, 22, 38, 54):
            draw.rectangle((x, 20, x + 5, 25), fill="#cc3355")

    source = _save(tmp_path, "batch.png", draw_details, size=(72, 48))
    baseline_dir = tmp_path / "baseline"
    batched_dir = tmp_path / "batched"
    baseline = trace_image(
        source,
        baseline_dir,
        TraceConfig(colors=2, underlap=1, simplify=1.0, min_area=1, path_batching="off"),
        include_comparisons=False,
    )["metrics"]
    batched = trace_image(
        source,
        batched_dir,
        TraceConfig(
            colors=2,
            underlap=1,
            simplify=1.0,
            min_area=1,
            path_batching="consecutive",
        ),
        include_comparisons=False,
    )["metrics"]
    baseline_pixels = np.asarray(Image.open(baseline_dir / "rendered.png").convert("RGB"))
    batched_pixels = np.asarray(Image.open(batched_dir / "rendered.png").convert("RGB"))
    assert np.array_equal(baseline_pixels, batched_pixels)
    assert baseline["region_count"] == batched["region_count"]
    assert batched["svg_element_count"] < baseline["svg_element_count"]
    assert batched["compound_path_count"] >= 1
    assert batched["subpath_count"] == baseline["subpath_count"]


def test_batching_splits_when_underlapped_geometry_can_interact(tmp_path: Path):
    source = _save(
        tmp_path,
        "overlap.png",
        lambda draw: (
            draw.rectangle((6, 20, 10, 24), fill="#cc3355"),
            draw.rectangle((12, 20, 16, 24), fill="#cc3355"),
            draw.rectangle((30, 20, 34, 24), fill="#cc3355"),
        ),
        size=(48, 40),
    )
    baseline_dir = tmp_path / "overlap-baseline"
    batched_dir = tmp_path / "overlap-batched"
    config = dict(colors=2, underlap=1, simplify=1.0, min_area=1)
    trace_image(
        source,
        baseline_dir,
        TraceConfig(**config, path_batching="off"),
        include_comparisons=False,
    )
    metrics = trace_image(
        source,
        batched_dir,
        TraceConfig(**config, path_batching="consecutive"),
        include_comparisons=False,
    )["metrics"]
    assert metrics["region_count"] == 4
    assert metrics["svg_element_count"] == 3
    assert np.array_equal(
        np.asarray(Image.open(baseline_dir / "rendered.png")),
        np.asarray(Image.open(batched_dir / "rendered.png")),
    )


def test_batch_safety_margin_crosses_spatial_bucket_boundaries(tmp_path: Path):
    source = _save(
        tmp_path,
        "bucket-boundary.png",
        lambda draw: (
            draw.rectangle((26, 20, 30, 24), fill="#cc3355"),
            draw.rectangle((33, 20, 37, 24), fill="#cc3355"),
            draw.rectangle((45, 20, 49, 24), fill="#cc3355"),
        ),
        size=(56, 40),
    )
    metrics = trace_image(
        source,
        tmp_path / "bucket-batched",
        TraceConfig(
            colors=2,
            underlap=1,
            simplify=1.0,
            min_area=1,
            path_batching="consecutive",
        ),
        include_comparisons=False,
    )["metrics"]
    assert metrics["region_count"] == 4
    assert metrics["svg_element_count"] == 3
