"""Benchmark: measure how close each method gets to a known look.

One command:

    .venv/bin/python bench/benchmark.py --photos ~/Pictures/lookmatch-test

How it works, for every known look L (built-in formulas, plus any .cube files
you add to bench/looks/):

1. Split your photos into reference photos and input photos that never
   overlap. L applied to the reference photos plays "another photographer's
   graded photos". (The same-scenes condition instead uses L applied to the
   input photos themselves: the easy case, an upper bound.)
2. Each method builds a LUT from the references and the inputs: no change,
   Reinhard transfer, plain optimal transport, and lookmatch.
3. Each LUT is applied to each input photo and compared with the right
   answer, L applied to that photo, pixel by pixel with ΔE 2000.

Results go to bench/RESULTS.md (a readable table) and bench/results.json
(every score). Photos are read at a reduced size (800 px on the long side by
default) to keep runs short; for RAW files the camera's own JPEG preview is
used, standing in for an unedited editor export. Photos are only read, never
changed, and never copied into the repo.
"""

import argparse
import io as stdlib_io
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import rawpy
from PIL import Image, ImageOps

import lookmatch
from lookmatch import io
from lookmatch.apply import apply_lut
from lookmatch.baselines import identity_lut, plain_ot_lut, reinhard_lut
from lookmatch.export.cube import Cube, read_cube
from lookmatch.metrics import delta_e_2000
from lookmatch.pipeline import DEFAULT_TRANSPORT_STRENGTH, collect_photos, fit

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import make_looks  # noqa: E402

METHODS = ("no change", "Reinhard", "plain OT", "lookmatch")
CONDITIONS = ("different scenes", "same scenes")
BASELINE_SAMPLES = 50_000  # per photo, for the baselines' pooled samples
# Each photo is scored on a fixed random sample of its pixels. A LUT changes
# every pixel independently, so this measures the same thing as scoring the
# whole photo, about 20 times faster (ΔE 2000 is the slow part).
SCORE_PIXELS = 20_000


def score_pixels(image: npt.ArrayLike) -> npt.NDArray[np.float64]:
    """Return the fixed sample of a photo's pixels that it is scored on."""
    return io.sample_pixels(image, max_pixels=SCORE_PIXELS, seed=1)


Photo = tuple[str, npt.NDArray[np.float32]]


@dataclass(frozen=True)
class Score:
    """One method on one input photo, for one look and one split."""

    look: str
    condition: str
    fold: int
    method: str
    photo: str
    mean_de: float  # mean ΔE 2000 against the right answer
    p95_de: float  # 95th percentile ΔE 2000


def builtin_looks() -> dict[str, Cube]:
    """Return the built-in known looks."""
    return {name: make_looks.make_look(name) for name in make_looks.ALL_LOOKS}


def user_looks(folder: Path) -> dict[str, Cube]:
    """Return any .cube files in a folder (not searched recursively)."""
    if not folder.is_dir():
        return {}
    return {p.stem: read_cube(p) for p in sorted(folder.glob("*.cube"))}


def _load_one(path: Path, max_side: int) -> npt.NDArray[np.float32]:
    if path.suffix.lower() in io.RAW_EXTENSIONS:
        with rawpy.imread(str(path)) as raw:
            thumb = raw.extract_thumb()
        if thumb.format == rawpy.ThumbFormat.JPEG:
            im = ImageOps.exif_transpose(Image.open(stdlib_io.BytesIO(thumb.data)))
            im = im.convert("RGB")
            im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            return np.asarray(im, dtype=np.float32) / 255.0
    image = io.load_image(path)
    im = Image.fromarray(np.round(np.clip(image, 0, 1) * 255).astype(np.uint8))
    im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return np.asarray(im, dtype=np.float32) / 255.0


def load_photos(folder: Path, max_side: int = 800) -> list[Photo]:
    """Load every photo in a folder at a reduced size, sorted by name."""
    return [(p.name, _load_one(p, max_side)) for p in collect_photos(folder)]


def folds(n: int, max_folds: int = 3) -> list[tuple[list[int], list[int]]]:
    """Split n photos into (reference, input) index lists that never overlap.

    About a third of the photos are references; each fold uses the next
    block of photos as references and all others as inputs.
    """
    n_ref = max(1, n // 3)
    count = min(max_folds, n // n_ref)
    out = []
    for k in range(count):
        ref = list(range(k * n_ref, (k + 1) * n_ref))
        out.append((ref, [i for i in range(n) if i not in ref]))
    return out


def _save(folder: Path, name: str, srgb: npt.ArrayLike) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    pixels = np.round(np.clip(np.asarray(srgb), 0, 1) * 255).astype(np.uint8)
    Image.fromarray(pixels).save(folder / f"{Path(name).stem}.png")


def _pooled(images: Sequence[npt.ArrayLike]) -> npt.NDArray[np.float64]:
    return np.vstack(
        [io.sample_pixels(im, max_pixels=BASELINE_SAMPLES) for im in images]
    )


def run(
    photos: list[Photo],
    looks: dict[str, Cube],
    max_folds: int = 3,
    workdir: Path = HERE / "work",
    conditions: Sequence[str] = CONDITIONS,
    transport_strength: float = DEFAULT_TRANSPORT_STRENGTH,
) -> list[Score]:
    """Score every method on every look, split and input photo."""
    if len(photos) < 3:
        raise ValueError(
            f"The benchmark needs at least 3 photos, found {len(photos)}. "
            "15 to 30 varied photos give meaningful results."
        )
    scores = []
    for look_name, look in looks.items():
        for condition in conditions:
            for k, (ref_idx, in_idx) in enumerate(folds(len(photos), max_folds)):
                inputs = [photos[i] for i in in_idx]
                if condition == "same scenes":
                    refs = [(f"ref_{n}", apply_lut(im, look)) for n, im in inputs]
                else:
                    refs = [(f"ref_{photos[i][0]}", apply_lut(photos[i][1], look))
                            for i in ref_idx]  # fmt: skip
                folder = workdir / look_name / condition.replace(" ", "_") / f"fold{k}"
                for name, im in refs:
                    _save(folder / "refs", name, im)
                for name, im in inputs:
                    _save(folder / "inputs", name, im)

                src = _pooled([im for _, im in inputs])
                dst = _pooled([im for _, im in refs])
                cubes = {
                    "no change": identity_lut(),
                    "Reinhard": reinhard_lut(src, dst),
                    "plain OT": plain_ot_lut(src, dst),
                    "lookmatch": fit(
                        folder / "refs",
                        folder / "inputs",
                        transport_strength=transport_strength,
                    ).cube,
                }
                for name, im in inputs:
                    pixels = score_pixels(im)
                    truth = apply_lut(pixels, look)
                    for method in METHODS:
                        de = delta_e_2000(apply_lut(pixels, cubes[method]), truth)
                        scores.append(
                            Score(
                                look_name,
                                condition,
                                k,
                                method,
                                name,
                                float(de.mean()),
                                float(np.percentile(de, 95)),
                            )
                        )
    return scores


def summarize(scores: list[Score]) -> list[dict[str, Any]]:
    """Average each method per condition, and count photos it made worse."""
    baseline = {
        (s.look, s.condition, s.fold, s.photo): s.mean_de
        for s in scores
        if s.method == "no change"
    }
    rows = []
    for condition in CONDITIONS:
        for method in METHODS:
            mine = [
                s for s in scores if s.condition == condition and s.method == method
            ]
            if not mine:
                continue
            worse = [
                s.mean_de > baseline[(s.look, s.condition, s.fold, s.photo)] + 1e-9
                for s in mine
            ]
            rows.append(
                {
                    "condition": condition,
                    "method": method,
                    "mean_de": float(np.mean([s.mean_de for s in mine])),
                    "p95_de": float(np.mean([s.p95_de for s in mine])),
                    "worse_than_no_change": float(np.mean(worse)),
                }
            )
    return rows


def _per_look(scores: list[Score], condition: str) -> list[str]:
    looks = list(dict.fromkeys(s.look for s in scores))
    lines = [
        "| Look | " + " | ".join(METHODS) + " |",
        "|---" * (len(METHODS) + 1) + "|",
    ]
    for look in looks:
        cells = []
        for method in METHODS:
            vals = [
                s.mean_de
                for s in scores
                if s.look == look and s.condition == condition and s.method == method
            ]
            cells.append(f"{np.mean(vals):.2f}" if vals else "–")
        lines.append(f"| {look} | " + " | ".join(cells) + " |")
    return lines


def write_report(
    scores: list[Score], setup: dict[str, Any], md_path: Path, json_path: Path
) -> None:
    """Write the readable table (Markdown) and every score (JSON)."""
    rows = summarize(scores)
    lines = [
        "# Benchmark results",
        "",
        "How close each method gets to a known look, on photos it never saw as "
        "references. Score: mean ΔE 2000 against the right answer (below about 1 "
        "is invisible; lower is better). Method: [bench/benchmark.py]"
        "(benchmark.py).",
        "",
        "## Setup",
        "",
    ]
    lines += [f"- {k.replace('_', ' ')}: {v}" for k, v in setup.items()]
    for condition in CONDITIONS:
        part = [r for r in rows if r["condition"] == condition]
        if not part:
            continue
        lines += [
            "",
            f"## {condition.capitalize()}",
            "",
            "| Method | Mean ΔE 2000 | 95th percentile "
            "| Photos made worse than no change |",
            "|---|---|---|---|",
        ]
        for r in part:
            lines.append(
                f"| {r['method']} | {r['mean_de']:.2f} | {r['p95_de']:.2f} | "
                f"{r['worse_than_no_change'] * 100:.0f}% |"
            )
        lines += ["", "Mean ΔE 2000 per look:", "", *_per_look(scores, condition)]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {"setup": setup, "summary": rows, "scores": [asdict(s) for s in scores]},
            indent=1,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark from the command line."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--photos", type=Path, required=True, help="folder of photos")
    parser.add_argument("--max-side", type=int, default=800)
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--quick", action="store_true", help="3 looks, 1 fold")
    parser.add_argument("--out", type=Path, default=HERE / "RESULTS.md")
    args = parser.parse_args(argv)

    photos = load_photos(args.photos.expanduser(), args.max_side)
    looks = {**builtin_looks(), **user_looks(HERE / "looks")}
    if args.quick:
        looks = dict(list(looks.items())[:3])
        args.folds = 1
    print(f"{len(photos)} photos, {len(looks)} looks, up to {args.folds} folds")
    scores = run(photos, looks, max_folds=args.folds)
    setup = {
        "date": date.today().isoformat(),
        "lookmatch_version": lookmatch.__version__,
        "photos": len(photos),
        "photo_size": f"{args.max_side} px long side",
        "looks": ", ".join(looks),
        "folds": len(folds(len(photos), args.folds)),
        "lookmatch_transport_strength": DEFAULT_TRANSPORT_STRENGTH,
    }
    write_report(scores, setup, args.out, args.out.with_name("results.json"))
    print(args.out.read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
