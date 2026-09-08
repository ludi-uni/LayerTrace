from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

import cv2
import numpy as np

from .core import Region
from .curves import PathStats, contour_path


@dataclass(frozen=True)
class StyleKey:
    fill: str
    stroke: str = "none"
    opacity: str = "1"
    fill_rule: str = "evenodd"
    transform: str | None = None


@dataclass(frozen=True)
class _PaintShape:
    region_id: int
    path_data: str
    style: StyleKey
    stats: PathStats
    contour_count: int
    bbox: tuple[int, int, int, int]


@dataclass
class _Batch:
    style: StyleKey
    shapes: list[_PaintShape] = field(default_factory=list)
    occupied: dict[tuple[int, int], list[tuple[int, int, int, int]]] = field(default_factory=dict)

    def can_add(self, shape: _PaintShape) -> bool:
        if self.style != shape.style:
            return False
        for cell in _bbox_cells(shape.bbox):
            if any(_boxes_intersect(shape.bbox, existing) for existing in self.occupied.get(cell, [])):
                return False
        return True

    def add(self, shape: _PaintShape) -> None:
        self.shapes.append(shape)
        for cell in _bbox_cells(shape.bbox):
            self.occupied.setdefault(cell, []).append(shape.bbox)


def _bbox_cells(
    bbox: tuple[int, int, int, int], cell_size: int = 32, margin: int = 1
):
    x0, y0, x1, y1 = bbox
    for cell_y in range((y0 - margin) // cell_size, (y1 + margin) // cell_size + 1):
        for cell_x in range((x0 - margin) // cell_size, (x1 + margin) // cell_size + 1):
            yield cell_x, cell_y


def _boxes_intersect(
    left: tuple[int, int, int, int], right: tuple[int, int, int, int]
) -> bool:
    margin = 1
    return not (
        left[2] + margin < right[0] - margin
        or right[2] + margin < left[0] - margin
        or left[3] + margin < right[1] - margin
        or right[3] + margin < left[1] - margin
    )


def _paint_bbox(mask: np.ndarray, offset: tuple[int, int]) -> tuple[int, int, int, int]:
    x, y, width, height = cv2.boundingRect(mask)
    x0, y0 = offset[0] + x, offset[1] + y
    return x0, y0, x0 + width - 1, y0 + height - 1


def _batch_shapes(shapes: list[_PaintShape], mode: str) -> list[_Batch]:
    if mode not in {"off", "consecutive"}:
        raise ValueError(f"unknown path batching mode: {mode}")
    batches: list[_Batch] = []
    for shape in shapes:
        if mode == "off" or not batches or not batches[-1].can_add(shape):
            batches.append(_Batch(shape.style))
        batches[-1].add(shape)
    return batches


def _path_for_mask(
    mask: np.ndarray,
    simplify: float,
    offset: tuple[int, int],
    curve_fit: str,
    curve_error: float,
) -> tuple[str, PathStats, int]:
    contours, _ = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    parts: list[str] = []
    vertices = 0
    lines = 0
    cubics = 0
    moves = 0
    closes = 0
    contour_count = 0
    for contour in contours:
        approx = cv2.approxPolyDP(contour, max(0.0, float(simplify)), True)
        points = approx.reshape(-1, 2)
        if len(points) < 3:
            x, y, width, height = cv2.boundingRect(contour)
            points = np.asarray(
                [(x, y), (x + width, y), (x + width, y + height), (x, y + height)],
                dtype=np.int32,
            )
        points = points + np.asarray(offset, dtype=np.int32)
        path, stats = contour_path(points, curve_fit=curve_fit, curve_error=curve_error)
        if not path:
            continue
        parts.append(path)
        contour_count += 1
        vertices += stats.vertices
        lines += stats.line_commands
        cubics += stats.cubic_commands
        moves += stats.move_commands
        closes += stats.close_commands
    return (
        " ".join(parts),
        PathStats(vertices, lines, cubics, moves, closes),
        contour_count,
    )


def _paint_mask(
    region: Region, pixels: int, canvas_width: int, canvas_height: int
) -> tuple[np.ndarray, tuple[int, int]]:
    x, y, width, height = region.bbox
    if pixels <= 0:
        return region.mask.astype(np.uint8), (x, y)
    radius = int(pixels)
    left = min(radius, x)
    top = min(radius, y)
    right = min(radius, canvas_width - (x + width))
    bottom = min(radius, canvas_height - (y + height))
    padded = np.zeros((height + top + bottom, width + left + right), dtype=np.uint8)
    padded[top : top + height, left : left + width] = region.mask
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1)
    )
    return cv2.dilate(padded, kernel, iterations=1), (x - left, y - top)


def write_svg(
    path: Path,
    width: int,
    height: int,
    ordered_regions: list[Region],
    underlap: int,
    simplify: float,
    curve_fit: str = "off",
    curve_error: float = 1.0,
    path_batching: str = "off",
) -> dict[str, object]:
    shapes: list[_PaintShape] = []
    total_vertices = 0
    total_lines = 0
    total_cubics = 0
    total_moves = 0
    total_closes = 0
    total_contours = 0
    last_index = len(ordered_regions) - 1
    for index, region in enumerate(ordered_regions):
        # The frontmost detail has nothing above it to hide expansion, so leave it exact.
        paint_mask, offset = _paint_mask(
            region, underlap if index < last_index else 0, width, height
        )
        path_data, path_stats, contour_count = _path_for_mask(
            paint_mask, simplify, offset, curve_fit, curve_error
        )
        if not path_data:
            continue
        red, green, blue = region.color
        shapes.append(
            _PaintShape(
                region_id=region.id,
                path_data=path_data,
                style=StyleKey(fill=f"#{red:02x}{green:02x}{blue:02x}"),
                stats=path_stats,
                contour_count=contour_count,
                bbox=_paint_bbox(paint_mask, offset),
            )
        )
        total_vertices += path_stats.vertices
        total_lines += path_stats.line_commands
        total_cubics += path_stats.cubic_commands
        total_moves += path_stats.move_commands
        total_closes += path_stats.close_commands
        total_contours += contour_count
    batches = _batch_shapes(shapes, path_batching)
    elements: list[str] = []
    for batch_index, batch in enumerate(batches, start=1):
        region_count = len(batch.shapes)
        element_id = (
            f"region-{batch.shapes[0].region_id:03d}"
            if region_count == 1
            else f"batch-{batch_index:05d}"
        )
        path_data = " ".join(shape.path_data for shape in batch.shapes)
        opacity = "" if batch.style.opacity == "1" else f' opacity="{batch.style.opacity}"'
        transform = "" if batch.style.transform is None else f' transform="{batch.style.transform}"'
        region_metadata = "" if region_count == 1 else f' data-region-count="{region_count}"'
        elements.append(
            f'  <path id="{element_id}" d="{escape(path_data)}" fill="{batch.style.fill}" '
            f'fill-rule="{batch.style.fill_rule}" stroke="{batch.style.stroke}"'
            f'{opacity}{region_metadata}{transform}/>'
        )
    svg = "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            *elements,
            "</svg>",
            "",
        ]
    )
    path.write_text(svg, encoding="utf-8")
    distribution = Counter(
        "1" if len(batch.shapes) == 1 else
        "2-4" if len(batch.shapes) <= 4 else
        "5-16" if len(batch.shapes) <= 16 else
        "17-64" if len(batch.shapes) <= 64 else
        "65+"
        for batch in batches
    )
    return {
        "svg_shape_count": len(batches),
        "svg_element_count": len(batches),
        "compound_path_count": sum(len(batch.shapes) > 1 for batch in batches),
        "batched_region_count": sum(len(batch.shapes) for batch in batches if len(batch.shapes) > 1),
        "subpath_count": total_contours,
        "batch_size_distribution": {
            key: distribution.get(key, 0) for key in ("1", "2-4", "5-16", "17-64", "65+")
        },
        "max_batch_size": max((len(batch.shapes) for batch in batches), default=0),
        "total_vertices": total_vertices,
        "total_path_commands": total_lines + total_cubics + total_moves + total_closes,
        "line_command_count": total_lines,
        "cubic_command_count": total_cubics,
        "control_point_count": total_cubics * 2,
        "move_command_count": total_moves,
        "close_command_count": total_closes,
        "contour_count": total_contours,
    }
