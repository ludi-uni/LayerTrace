from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True)
class PathStats:
    vertices: int = 0
    line_commands: int = 0
    cubic_commands: int = 0
    move_commands: int = 0
    close_commands: int = 0

    @property
    def total_commands(self) -> int:
        return self.line_commands + self.cubic_commands + self.move_commands + self.close_commands


@dataclass(frozen=True)
class _Line:
    end: np.ndarray


@dataclass(frozen=True)
class _Cubic:
    control1: np.ndarray
    control2: np.ndarray
    end: np.ndarray


def _number(value: float) -> str:
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _point(point: np.ndarray) -> str:
    return f"{_number(float(point[0]))},{_number(float(point[1]))}"


def _serialize(commands: list[_Line | _Cubic]) -> str:
    parts: list[str] = []
    for command in commands:
        if isinstance(command, _Line):
            parts.append(f"L{_point(command.end)}")
        else:
            parts.append(
                f"C{_point(command.control1)} {_point(command.control2)} {_point(command.end)}"
            )
    return " ".join(parts)


def _unit(vector: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    if length <= 1e-9:
        return np.zeros(2, dtype=float)
    return vector / length


def _solve_controls(
    points: np.ndarray,
    parameters: np.ndarray,
    tangent1: np.ndarray,
    tangent2: np.ndarray,
) -> _Cubic:
    p0 = points[0]
    p3 = points[-1]
    t = parameters[:, None]
    omt = 1.0 - t
    b0 = omt**3
    b1 = 3.0 * omt**2 * t
    b2 = 3.0 * omt * t**2
    b3 = t**3
    base = (b0 + b1) * p0 + (b2 + b3) * p3
    a1 = b1 * tangent1
    a2 = b2 * tangent2
    residual = points - base
    matrix = np.asarray(
        [
            [np.sum(a1 * a1), np.sum(a1 * a2)],
            [np.sum(a1 * a2), np.sum(a2 * a2)],
        ],
        dtype=float,
    )
    target = np.asarray([np.sum(a1 * residual), np.sum(a2 * residual)], dtype=float)
    try:
        alpha1, alpha2 = np.linalg.solve(matrix, target)
    except np.linalg.LinAlgError:
        alpha1 = alpha2 = float(np.linalg.norm(p3 - p0)) / 3.0
    if alpha1 <= 1e-6 or alpha2 <= 1e-6:
        alpha1 = alpha2 = float(np.linalg.norm(p3 - p0)) / 3.0
    control1 = p0 + tangent1 * alpha1
    control2 = p3 + tangent2 * alpha2
    return _Cubic(control1, control2, p3.copy())


def _evaluate(command: _Cubic, start: np.ndarray, parameters: np.ndarray) -> np.ndarray:
    t = parameters[:, None]
    omt = 1.0 - t
    return (
        omt**3 * start
        + 3.0 * omt**2 * t * command.control1
        + 3.0 * omt * t**2 * command.control2
        + t**3 * command.end
    )


def _reparameterize(
    points: np.ndarray, start: np.ndarray, command: _Cubic, parameters: np.ndarray
) -> np.ndarray:
    updated = parameters.copy()
    p0, p1, p2, p3 = start, command.control1, command.control2, command.end
    for index in range(1, len(points) - 1):
        t = float(parameters[index])
        omt = 1.0 - t
        point = (
            omt**3 * p0
            + 3.0 * omt**2 * t * p1
            + 3.0 * omt * t**2 * p2
            + t**3 * p3
        )
        first = (
            3.0 * omt**2 * (p1 - p0)
            + 6.0 * omt * t * (p2 - p1)
            + 3.0 * t**2 * (p3 - p2)
        )
        second = 6.0 * omt * (p2 - 2.0 * p1 + p0) + 6.0 * t * (p3 - 2.0 * p2 + p1)
        delta = point - points[index]
        denominator = float(np.dot(first, first) + np.dot(delta, second))
        if abs(denominator) > 1e-9:
            updated[index] = np.clip(t - float(np.dot(delta, first)) / denominator, 0.0, 1.0)
    # Preserve point order along the curve after Newton updates.
    for index in range(1, len(updated) - 1):
        lower = updated[index - 1] + 1e-6
        upper = 1.0 - (len(updated) - 1 - index) * 1e-6
        updated[index] = np.clip(updated[index], lower, upper)
    updated[-1] = 1.0
    return updated


def _fit_cubic(points: np.ndarray) -> tuple[_Cubic, np.ndarray]:
    p0 = points[0]
    p3 = points[-1]
    distances = np.linalg.norm(np.diff(points, axis=0), axis=1)
    total = float(distances.sum())
    if total <= 1e-9:
        command = _Cubic(p0.copy(), p3.copy(), p3.copy())
        return command, np.zeros(len(points), dtype=float)
    parameters = np.concatenate(([0.0], np.cumsum(distances) / total))
    tangent1 = _unit(points[1] - p0)
    tangent2 = _unit(points[-2] - p3)
    command = _solve_controls(points, parameters, tangent1, tangent2)
    for _ in range(4):
        parameters = _reparameterize(points, p0, command, parameters)
        command = _solve_controls(points, parameters, tangent1, tangent2)
    fitted = _evaluate(command, p0, parameters)
    errors = np.linalg.norm(fitted - points, axis=1)
    return command, errors


def _line_errors(points: np.ndarray) -> np.ndarray:
    start, end = points[0], points[-1]
    direction = end - start
    length = float(np.linalg.norm(direction))
    if length <= 1e-9:
        return np.linalg.norm(points - start, axis=1)
    relative = points - start
    return np.abs(direction[0] * relative[:, 1] - direction[1] * relative[:, 0]) / length


def _fit_chain(
    points: np.ndarray, error: float, depth: int = 0, compare_size: bool = True
) -> list[_Line | _Cubic]:
    if len(points) <= 2:
        return [_Line(points[-1].copy())]
    if float(_line_errors(points).max()) <= max(0.1, error * 0.35):
        return [_Line(points[-1].copy())]
    cubic, errors = _fit_cubic(points)
    max_index = int(np.argmax(errors))
    if float(errors[max_index]) <= error:
        fitted: list[_Line | _Cubic] = [cubic]
    elif depth >= 16 or max_index <= 0 or max_index >= len(points) - 1:
        fitted = [_Line(point.copy()) for point in points[1:]]
    else:
        fitted = _fit_chain(points[: max_index + 1], error, depth + 1, False)
        fitted.extend(_fit_chain(points[max_index:], error, depth + 1, False))
    line_fallback = [_Line(point.copy()) for point in points[1:]]
    if compare_size and (
        len(fitted) >= len(line_fallback)
        or len(_serialize(fitted)) >= len(_serialize(line_fallback))
    ):
        return line_fallback
    return fitted


def _corner_indices(points: np.ndarray, threshold_degrees: float = 55.0) -> list[int]:
    corners: list[int] = []
    threshold = math.radians(threshold_degrees)
    for index in range(len(points)):
        incoming = _unit(points[index] - points[index - 1])
        outgoing = _unit(points[(index + 1) % len(points)] - points[index])
        cosine = float(np.clip(np.dot(incoming, outgoing), -1.0, 1.0))
        if math.acos(cosine) >= threshold:
            corners.append(index)
    return corners


def _smooth_anchors(count: int) -> list[int]:
    anchor_count = min(4, max(2, count // 4))
    return sorted({(index * count) // anchor_count for index in range(anchor_count)})


def _line_path(points: np.ndarray) -> tuple[str, PathStats]:
    path = f"M{_point(points[0])} " + " ".join(f"L{_point(point)}" for point in points[1:]) + " Z"
    return path, PathStats(
        vertices=len(points),
        line_commands=len(points) - 1,
        move_commands=1,
        close_commands=1,
    )


def contour_path(
    points: np.ndarray, *, curve_fit: str, curve_error: float
) -> tuple[str, PathStats]:
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    if len(points) < 3:
        return "", PathStats()
    if curve_fit == "off":
        return _line_path(points)
    if curve_fit != "cubic":
        raise ValueError(f"unknown curve fit mode: {curve_fit}")
    # Short contours are both cheaper and more compact as lines; fitting only
    # long contours keeps curve analysis from scaling with region explosion.
    if len(points) < 128:
        return _line_path(points)

    anchors = _corner_indices(points)
    if len(anchors) < 2:
        anchors = _smooth_anchors(len(points))
    anchors = sorted(set(anchors))
    commands: list[_Line | _Cubic] = []
    for anchor_index, start in enumerate(anchors):
        end = anchors[(anchor_index + 1) % len(anchors)]
        if end > start:
            chain = points[start : end + 1]
        else:
            chain = np.vstack((points[start:], points[: end + 1]))
        segment_commands = _fit_chain(chain, max(0.05, float(curve_error)))
        if (
            anchor_index == len(anchors) - 1
            and segment_commands
            and isinstance(segment_commands[-1], _Line)
            and np.allclose(segment_commands[-1].end, points[anchors[0]])
        ):
            segment_commands = segment_commands[:-1]
        commands.extend(segment_commands)

    line_count = sum(isinstance(command, _Line) for command in commands)
    cubic_count = sum(isinstance(command, _Cubic) for command in commands)
    # Vertices are on-curve anchors; cubic control points are tracked separately.
    coordinate_points = 1 + line_count + cubic_count
    body = _serialize(commands)
    path = f"M{_point(points[anchors[0]])}{(' ' + body) if body else ''} Z"
    return path, PathStats(
        vertices=coordinate_points,
        line_commands=line_count,
        cubic_commands=cubic_count,
        move_commands=1,
        close_commands=1,
    )
