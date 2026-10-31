"""Check that editing apps apply a lookmatch .cube the same way lookmatch does.

Task 1.5. Open tests/fixtures/test_chart.png in an app, apply
tests/fixtures/test_look_33.cube, export a PNG, then run:

    .venv/bin/python bench/app_check.py Photoshop=~/Desktop/lookmatch-qa/photoshop.png

You can pass several exports at once. For every flat patch on the chart, the
script compares the app's colors with lookmatch's own result, in 8-bit levels
(0 to 255). See docs/qa-app-check.md for the full guide.
"""

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from PIL import Image

from lookmatch import io
from lookmatch.apply import apply_lut
from lookmatch.export.cube import read_cube

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

PASS_LEVELS = 2  # at most 2 of 255 levels on any patch: invisible
CLOSE_LEVELS = 4  # up to 4: very small, but worth a look

U8 = npt.NDArray[np.uint8]


def chart() -> tuple[U8, dict[str, Any]]:
    """Return the test chart pixels and its patch layout."""
    pixels = np.asarray(Image.open(FIXTURES / "test_chart.png").convert("RGB"))
    layout = json.loads((FIXTURES / "test_chart.json").read_text())
    return pixels, layout


def expected_pixels() -> U8:
    """Return the test chart with the test LUT applied by lookmatch, in 8-bit."""
    pixels, _ = chart()
    look = read_cube(FIXTURES / "test_look_33.cube")
    out = apply_lut(pixels / 255.0, look)
    return np.round(np.clip(out, 0, 1) * 255).astype(np.uint8)


def _measure(
    pixels: npt.NDArray[Any], patch: dict[str, Any]
) -> npt.NDArray[np.float64]:
    """Median color of a patch's center, ignoring a 25% border on each side."""
    x, y, w, h = patch["x"], patch["y"], patch["w"], patch["h"]
    region = pixels[y + h // 4 : y + h - h // 4, x + w // 4 : x + w - w // 4]
    return np.median(region.reshape(-1, 3).astype(np.float64), axis=0)


@dataclass
class Report:
    """The result of comparing one app's export with lookmatch."""

    verdict: str  # "pass", "close", "fail", "not applied" or "wrong size"
    message: str
    max_diff: float = 0.0
    mean_diff: float = 0.0
    by_group: dict[str, float] = field(default_factory=dict)
    worst: list[tuple[str, list[int], list[int], float]] = field(default_factory=list)


def compare(export_path: str | Path) -> Report:
    """Compare an app's export of the chart with lookmatch's own result."""
    original, layout = chart()
    expected = expected_pixels()
    got = np.round(np.clip(io.load_image(export_path), 0, 1) * 255)

    want_w, want_h = layout["size"]
    if got.shape[:2] != (want_h, want_w):
        return Report(
            "wrong size",
            f"The export is {got.shape[1]} x {got.shape[0]} pixels, but the chart is "
            f"{want_w} x {want_h}. The app resized or cropped it, so the patches "
            "don't line up. Export at the original size with no scaling.",
        )

    rows = []
    for patch in layout["patches"]:
        e, g, o = (_measure(p, patch) for p in (expected, got, original))
        rows.append(
            (patch, e, g, float(np.max(np.abs(g - e))), float(np.max(np.abs(g - o))))
        )

    diffs = np.array([r[3] for r in rows])
    to_original = np.mean([r[4] for r in rows])
    lut_strength = np.mean(
        [np.max(np.abs(r[1] - _measure(original, r[0]))) for r in rows]
    )
    by_group: dict[str, float] = {}
    for patch, *_, diff, _ in rows:
        by_group[patch["group"]] = max(by_group.get(patch["group"], 0.0), diff)
    worst = sorted(rows, key=lambda r: -r[3])[:5]
    report = Report(
        verdict="",
        message="",
        max_diff=float(diffs.max()),
        mean_diff=float(diffs.mean()),
        by_group=by_group,
        worst=[
            (r[0]["name"], r[1].astype(int).tolist(), r[2].astype(int).tolist(), r[3])
            for r in worst
        ],
    )

    if to_original < 1.0 and lut_strength > 3.0:
        report.verdict = "not applied"
        report.message = (
            "The export looks like the original chart: the LUT wasn't applied, "
            "or it was turned off before exporting."
        )
    elif report.max_diff <= PASS_LEVELS:
        report.verdict = "pass"
        report.message = (
            f"Every patch is within {PASS_LEVELS} levels of lookmatch. The app "
            "applies the LUT the same way."
        )
    elif report.max_diff <= CLOSE_LEVELS:
        report.verdict = "close"
        report.message = (
            f"Every patch is within {CLOSE_LEVELS} levels, which is hard to see, "
            "but more than rounding alone. Usually a different interpolation "
            "setting. Send the result to Claude."
        )
    else:
        report.verdict = "fail"
        report.message = (
            f"Some patches are clearly different (up to {report.max_diff:.0f} levels). "
            "The app is probably converting colors (a color profile or color "
            "management setting) or the wrong LUT was loaded. Send the result "
            "to Claude."
        )
    return report


def format_report(app: str, report: Report) -> str:
    """Format a report as plain text."""
    lines = [f"{app}: {report.verdict.upper()}", f"  {report.message}"]
    if report.by_group:
        lines.append(
            f"  Largest difference: {report.max_diff:.1f} levels, "
            f"average {report.mean_diff:.2f} levels"
        )
        groups = ", ".join(f"{g} {d:.1f}" for g, d in report.by_group.items())
        lines.append(f"  Largest by group: {groups}")
        lines.append("  Worst patches (lookmatch -> app):")
        for name, want, got, diff in report.worst:
            lines.append(f"    {name:<16} {want} -> {got}  ({diff:.0f} levels)")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    """Compare each export given as NAME=PATH (or just PATH)."""
    if not argv:
        print(__doc__)
        return 2
    ok = True
    for arg in argv:
        name, _, path = arg.rpartition("=")
        path = str(Path(path).expanduser())
        name = name or Path(path).stem
        if not Path(path).is_file():
            print(f"{name}: can't find {path}")
            ok = False
            continue
        report = compare(path)
        print(format_report(name, report) + "\n")
        ok = ok and report.verdict in ("pass", "close")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
