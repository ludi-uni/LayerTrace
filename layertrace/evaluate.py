"""Small, reproducible evaluation runner for the five-image Phase 2 matrix."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from time import perf_counter

from PIL import Image, ImageDraw, ImageOps

from .pipeline import TraceConfig, trace_image


UNDERLAPS = (0, 1, 2, 4)
ORDERINGS = ("area", "containment")
ROLES = {
    "test_1": "simple baseline",
    "test_2": "hair complexity",
    "test_3": "similar adjacent colors",
    "test_4": "complex background",
    "test_5": "fine highlights",
}
BEST_CONDITIONS = {test_id: {"ordering": "containment", "underlap": 1} for test_id in ROLES}
FAILURE_MODES = {
    "test_1": ["thin hair shading is simplified", "minor contour speckle remains"],
    "test_2": ["small detached hair locks lose edge fidelity", "fine hair highlights fragment"],
    "test_3": ["subtle blue-gray boundaries flatten", "minor clothing boundary bleed remains"],
    "test_4": ["plant and shelf details become noisy", "dense clothing regions retain speckle"],
    "test_5": ["thin hair and clothing highlights fragment", "many tiny highlight regions inflate shape count"],
}


def evaluation_matrix() -> list[tuple[str, int]]:
    return [(ordering, underlap) for ordering in ORDERINGS for underlap in UNDERLAPS]


def _git_head(repo: Path) -> tuple[str | None, str]:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout.strip(), "available"
    return None, "unborn"


def _implementation_digest(repo: Path) -> str:
    digest = hashlib.sha256()
    paths = [
        repo / "layertrace" / "core.py",
        repo / "layertrace" / "pipeline.py",
        repo / "layertrace" / "svg.py",
        repo / "pyproject.toml",
    ]
    for path in paths:
        digest.update(path.relative_to(repo).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _input_files(input_dir: Path) -> list[Path]:
    files = sorted(
        (path for path in input_dir.iterdir() if path.suffix.lower() in {".png", ".jpg", ".jpeg"}),
        key=lambda path: path.name.lower(),
    )
    if len(files) != 5:
        raise ValueError(f"expected exactly 5 images in {input_dir}, found {len(files)}")
    return files


def _write_sweep_grid(test_dir: Path, test_id: str) -> None:
    panels: list[tuple[str, Path]] = [
        ("source", test_dir / "area" / "underlap_0" / "source.png"),
        ("quantized", test_dir / "area" / "underlap_0" / "quantized.png"),
    ]
    panels.extend(
        (f"{ordering} u={underlap}", test_dir / ordering / f"underlap_{underlap}" / "rendered.png")
        for ordering, underlap in evaluation_matrix()
    )
    tile = 260
    label_height = 24
    grid = Image.new("RGB", (tile * 5, (tile + label_height) * 2), "white")
    draw = ImageDraw.Draw(grid)
    for index, (label, path) in enumerate(panels):
        image = Image.open(path).convert("RGB")
        fitted = ImageOps.contain(image, (tile, tile), Image.Resampling.LANCZOS)
        x = (index % 5) * tile
        y = (index // 5) * (tile + label_height) + label_height
        grid.paste(fitted, (x + (tile - fitted.width) // 2, y + (tile - fitted.height) // 2))
        draw.text((x + 5, y - label_height + 4), label, fill="black")
    grid.save(test_dir / "sweep_grid.png")


def write_best_comparison_grids(output_dir: Path) -> None:
    tile = 280
    label_height = 24
    combined = Image.new("RGB", (tile * 4, (tile + label_height) * 5), "white")
    combined_draw = ImageDraw.Draw(combined)
    best_records: list[dict] = []
    for row, test_id in enumerate(ROLES):
        condition = BEST_CONDITIONS[test_id]
        run_dir = output_dir / test_id / condition["ordering"] / f"underlap_{condition['underlap']}"
        metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
        panels = [
            ("source", run_dir / "source.png"),
            ("quantized", run_dir / "quantized.png"),
            ("rendered", run_dir / "rendered.png"),
            ("diff", run_dir / "diff.png"),
        ]
        local = Image.new("RGB", (tile * 4, tile + label_height), "white")
        local_draw = ImageDraw.Draw(local)
        for column, (label, path) in enumerate(panels):
            image = Image.open(path).convert("RGB")
            fitted = ImageOps.contain(image, (tile, tile), Image.Resampling.LANCZOS)
            x = column * tile
            y = label_height
            local.paste(fitted, (x + (tile - fitted.width) // 2, y + (tile - fitted.height) // 2))
            local_draw.text((x + 5, 4), f"{test_id} {label}", fill="black")
            combined.paste(
                fitted,
                (
                    x + (tile - fitted.width) // 2,
                    row * (tile + label_height) + label_height + (tile - fitted.height) // 2,
                ),
            )
            combined_draw.text(
                (x + 5, row * (tile + label_height) + 4), f"{test_id} {label}", fill="black"
            )
        local.save(output_dir / test_id / "best_comparison.png")
        best_records.append(
            {
                "test_id": test_id,
                **condition,
                "metrics": metrics,
                "failure_modes": FAILURE_MODES[test_id],
            }
        )
    combined.save(output_dir / "comparison_grid.png")
    (output_dir / "best_conditions.json").write_text(
        json.dumps(best_records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    summary_path = output_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["best_conditions"] = best_records
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def run_evaluation(input_dir: Path, output_dir: Path) -> list[dict]:
    repo = Path(__file__).resolve().parents[1]
    input_dir = input_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    git_head, git_state = _git_head(repo)
    implementation_sha256 = _implementation_digest(repo)
    rows: list[dict] = []

    for index, input_path in enumerate(_input_files(input_dir), start=1):
        test_id = f"test_{index}"
        with Image.open(input_path) as image:
            width, height = image.size
        for ordering, underlap in evaluation_matrix():
            run_dir = output_dir / test_id / ordering / f"underlap_{underlap}"
            started_at = datetime.now(timezone.utc).isoformat()
            started = perf_counter()
            report = trace_image(
                input_path,
                run_dir,
                TraceConfig(
                    colors=32,
                    simplify=1.0,
                    ordering=ordering,
                    underlap=underlap,
                ),
                include_comparisons=False,
            )
            runtime_ms = (perf_counter() - started) * 1000.0
            metrics = report["metrics"]
            metrics["runtime_ms"] = runtime_ms
            metrics["svg_file_size_bytes"] = (run_dir / "output.svg").stat().st_size
            (run_dir / "metrics.json").write_text(
                json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            run_data = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            run_data["evaluation"] = {
                "test_id": test_id,
                "role": ROLES[test_id],
                "input_path": input_path.relative_to(repo).as_posix(),
                "image_size": [width, height],
                "random_seed": None,
                "layertrace_git_head": git_head,
                "git_head_state": git_state,
                "implementation_sha256": implementation_sha256,
                "timestamp_utc": started_at,
            }
            run_data["metrics"] = metrics
            (run_dir / "run.json").write_text(
                json.dumps(run_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            rows.append(
                {
                    "test_id": test_id,
                    "role": ROLES[test_id],
                    "input_file": input_path.name,
                    "ordering": ordering,
                    "underlap": underlap,
                    "mean_absolute_rgb_error": metrics["mean_absolute_rgb_error"],
                    "max_rgb_error": metrics["max_rgb_error"],
                    "different_pixel_ratio": metrics["different_pixel_ratio"],
                    "white_gap_pixel_count": metrics["white_gap_pixel_count"],
                    "region_count": metrics["region_count"],
                    "svg_shape_count": metrics["svg_shape_count"],
                    "total_vertices": metrics["total_vertices"],
                    "runtime_ms": runtime_ms,
                    "svg_file_size_bytes": metrics["svg_file_size_bytes"],
                }
            )
        _write_sweep_grid(output_dir / test_id, test_id)

    summary = {
        "evaluation": {
            "total_runs": len(rows),
            "colors": 32,
            "simplify": 1.0,
            "underlap_values": list(UNDERLAPS),
            "ordering_modes": list(ORDERINGS),
            "random_seed": None,
            "layertrace_git_head": git_head,
            "git_head_state": git_state,
            "implementation_sha256": implementation_sha256,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
        "runs": rows,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with (output_dir / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_best_comparison_grids(output_dir)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("examples/test_pic"))
    parser.add_argument("--output", type=Path, default=Path("out/test-set-evaluation"))
    args = parser.parse_args(argv)
    rows = run_evaluation(args.input_dir, args.output)
    print(f"completed {len(rows)} runs in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
