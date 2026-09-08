from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image


RGB = tuple[int, int, int]


@dataclass
class Region:
    id: int
    label: int
    color: RGB
    area: int
    bbox: tuple[int, int, int, int]
    centroid: tuple[float, float]
    mask: np.ndarray = field(repr=False, compare=False)
    contours: list[np.ndarray] = field(repr=False, compare=False)
    parent_id: int | None = None
    containment_depth: int = 0


def quantize_image(
    image: Image.Image, colors: int, smoothing: float = 0.0
) -> tuple[np.ndarray, dict[int, RGB], Image.Image]:
    """Convert an opaque RGB image into stable palette labels."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    if smoothing > 0:
        sigma = float(smoothing)
        rgb = cv2.GaussianBlur(rgb, (0, 0), sigmaX=sigma, sigmaY=sigma)
    quantized = Image.fromarray(rgb).quantize(
        colors=max(2, min(256, int(colors))),
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.NONE,
    )
    labels = np.asarray(quantized, dtype=np.int32)
    raw_palette = np.asarray(quantized.getpalette(), dtype=np.uint8).reshape(-1, 3)
    used = np.unique(labels)
    palette = {int(label): tuple(int(v) for v in raw_palette[label]) for label in used}
    return labels, palette, quantized.convert("RGB")


def labels_to_rgb(labels: np.ndarray, palette: dict[int, RGB]) -> np.ndarray:
    """Expand palette labels with one indexed raster lookup."""
    highest = max(palette, default=0)
    lookup = np.zeros((highest + 1, 3), dtype=np.uint8)
    for label, color in palette.items():
        lookup[label] = color
    return lookup[labels]


def merge_small_components(labels: np.ndarray, min_area: int) -> np.ndarray:
    """Merge tiny components into the most common touching label."""
    if min_area <= 1:
        return labels.copy()
    merged = labels.copy()
    kernel = np.ones((3, 3), np.uint8)
    # Two passes handle isolated specks without turning this into segmentation work.
    for _ in range(2):
        changed = False
        for label in np.unique(merged):
            binary = (merged == label).astype(np.uint8)
            count, components, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
            for component in range(1, count):
                area = int(stats[component, cv2.CC_STAT_AREA])
                if area >= min_area:
                    continue
                x = int(stats[component, cv2.CC_STAT_LEFT])
                y = int(stats[component, cv2.CC_STAT_TOP])
                width = int(stats[component, cv2.CC_STAT_WIDTH])
                height = int(stats[component, cv2.CC_STAT_HEIGHT])
                x0, y0 = max(0, x - 1), max(0, y - 1)
                x1 = min(merged.shape[1], x + width + 1)
                y1 = min(merged.shape[0], y + height + 1)
                local_components = components[y0:y1, x0:x1]
                local_labels = merged[y0:y1, x0:x1]
                mask = local_components == component
                ring = cv2.dilate(mask.astype(np.uint8), kernel, iterations=1).astype(bool) & ~mask
                neighbors = local_labels[ring]
                neighbors = neighbors[neighbors != label]
                if neighbors.size:
                    values, counts = np.unique(neighbors, return_counts=True)
                    local_labels[mask] = int(values[np.argmax(counts)])
                    changed = True
        if not changed:
            break
    return merged


def _region_contours(mask: np.ndarray, offset: tuple[int, int] = (0, 0)) -> list[np.ndarray]:
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if offset != (0, 0):
        shift = np.asarray(offset, dtype=np.int32).reshape(1, 1, 2)
        contours = [contour + shift for contour in contours]
    return contours


def extract_regions(
    labels: np.ndarray, palette: dict[int, RGB], min_area: int = 1
) -> list[Region]:
    regions: list[Region] = []
    next_id = 1
    for label in sorted(int(value) for value in np.unique(labels)):
        binary = (labels == label).astype(np.uint8)
        count, components, stats, centroids = cv2.connectedComponentsWithStats(binary, 8)
        for component in range(1, count):
            area = int(stats[component, cv2.CC_STAT_AREA])
            if area < min_area:
                continue
            x = int(stats[component, cv2.CC_STAT_LEFT])
            y = int(stats[component, cv2.CC_STAT_TOP])
            width = int(stats[component, cv2.CC_STAT_WIDTH])
            height = int(stats[component, cv2.CC_STAT_HEIGHT])
            mask = components[y : y + height, x : x + width] == component
            regions.append(
                Region(
                    id=next_id,
                    label=label,
                    color=palette[label],
                    area=area,
                    bbox=(x, y, width, height),
                    centroid=(float(centroids[component][0]), float(centroids[component][1])),
                    mask=mask,
                    contours=_region_contours(mask, (x, y)),
                )
            )
            next_id += 1
    _assign_containment(regions)
    return regions


def _assign_containment(regions: list[Region]) -> None:
    if not regions:
        return
    cell_size = 64
    buckets: dict[tuple[int, int], list[int]] = {}
    outer_contours: list[np.ndarray | None] = []
    for index, region in enumerate(regions):
        x, y, width, height = region.bbox
        for cell_y in range(y // cell_size, (y + height - 1) // cell_size + 1):
            for cell_x in range(x // cell_size, (x + width - 1) // cell_size + 1):
                buckets.setdefault((cell_x, cell_y), []).append(index)
        outer_contours.append(max(region.contours, key=cv2.contourArea, default=None))

    for child in regions:
        containers: list[Region] = []
        point = child.centroid
        cell = (int(point[0]) // cell_size, int(point[1]) // cell_size)
        for candidate_index in buckets.get(cell, []):
            candidate = regions[candidate_index]
            if candidate.id == child.id or candidate.area <= child.area:
                continue
            x, y, width, height = candidate.bbox
            if not (x <= point[0] <= x + width - 1 and y <= point[1] <= y + height - 1):
                continue
            outer = outer_contours[candidate_index]
            if outer is not None and cv2.pointPolygonTest(outer, point, False) >= 0:
                containers.append(candidate)
        child.containment_depth = len(containers)
        if containers:
            child.parent_id = min(containers, key=lambda region: region.area).id


def order_regions(regions: list[Region], mode: str = "containment") -> list[Region]:
    """Return explicit back-to-front paint order."""
    if mode == "area":
        return sorted(regions, key=lambda region: (-region.area, region.id))
    if mode != "containment":
        raise ValueError(f"unknown ordering mode: {mode}")
    return sorted(
        regions,
        key=lambda region: (region.containment_depth, -region.area, region.id),
    )


def expanded_mask(mask: np.ndarray, pixels: int) -> np.ndarray:
    if pixels <= 0:
        return mask.astype(np.uint8)
    radius = int(pixels)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
    return cv2.dilate(mask.astype(np.uint8), kernel, iterations=1)
