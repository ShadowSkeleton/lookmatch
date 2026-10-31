"""The full pipeline: reference photos and your photos in, a fitted look out.

fit() runs every step in order (see docs/method.md for each one):

0. Load each photo and sample its pixels. Photos are loaded one at a time
   and dropped after sampling, so memory stays low with many photos.
1. Neutralize: measure each photo's light and exposure, and move each photo
   toward its own group's average (references as one group, yours as the
   other).
2. Fit the look on the pooled samples: tone curve, then split toning, then
   sliced optimal transport for what remains.
3. In portrait mode only, cap how far skin hue may rotate.
4. Bake the 33-point LUT, falling back to tone curve plus split toning for
   colors your photos never contain.

Every photo contributes the same number of samples, the total per side is
capped so large folders stay fast, and every random step uses one fixed seed,
so the same photos always give the same LUT and a byte-identical look.json.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from lookmatch import io, neutralize, skin, tone, toning, transport
from lookmatch.apply import apply_lut
from lookmatch.bake import LUT_SIZE, PRIOR_PULL, SMOOTHNESS, BakeResult, bake_lut
from lookmatch.export.cube import Cube, identity_table
from lookmatch.look import Look, Photo

# Not yet tuned: the benchmark (Phase 6) will choose this from measured
# results. 0.5 is a cautious start, because full strength forces one
# scene's colors onto another when the scenes differ (docs/method.md).
DEFAULT_TRANSPORT_STRENGTH = 0.5
MAX_POOLED_SAMPLES = 200_000  # per side, split evenly between photos

FloatArray = npt.NDArray[np.floating[Any]]
PhotoSource = str | Path | Sequence[str | Path]
SUPPORTED = io.IMAGE_EXTENSIONS | io.RAW_EXTENSIONS


@dataclass(frozen=True)
class FitResult:
    """A fitted look: the record, the LUT, and the bake checks."""

    look: Look
    cube: Cube
    bake: BakeResult


@dataclass(frozen=True)
class _Sampled:
    path: Path
    source: str  # "raw" or "rendered"
    pixels: FloatArray  # sRGB samples
    estimate: neutralize.Estimate


def collect_photos(source: PhotoSource) -> list[Path]:
    """List the photos in a file, a folder, or a list of files, sorted by name.

    Folders are not searched recursively. Hidden files and files that aren't
    JPEG, PNG, TIFF or camera RAW are skipped.
    """
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Can't find '{path}'. Check the path.")
        if path.is_file():
            return [path]
        candidates = list(path.iterdir())
    else:
        candidates = [Path(p) for p in source]
        for p in candidates:
            if not p.exists():
                raise FileNotFoundError(f"Can't find '{p}'. Check the path.")
    photos = [
        p
        for p in candidates
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in SUPPORTED
    ]
    return sorted(photos, key=lambda p: p.name)


def _sample_group(
    paths: list[Path], what: str, seed: int
) -> tuple[list[_Sampled], int]:
    if not paths:
        raise ValueError(
            f"Found no photos for the {what}. Use JPEG, PNG, TIFF or camera RAW files."
        )
    per_photo = min(io.MAX_SAMPLES, MAX_POOLED_SAMPLES // len(paths))
    sampled = []
    for path in paths:
        image = io.load_image(path)
        pixels = io.sample_pixels(image, max_pixels=per_photo, seed=seed)
        del image  # keep memory low: only the samples are needed
        source = "raw" if path.suffix.lower() in io.RAW_EXTENSIONS else "rendered"
        sampled.append(_Sampled(path, source, pixels, neutralize.estimate(pixels)))
    return sampled, per_photo


def _neutralized(
    group: list[_Sampled],
) -> tuple[npt.NDArray[np.float64], list[neutralize.Correction]]:
    corrections = neutralize.group_corrections([s.estimate for s in group])
    pooled = np.vstack(
        [
            np.clip(neutralize.apply_correction(s.pixels, c), 0.0, 1.0)
            for s, c in zip(group, corrections, strict=True)
        ]
    )
    return np.asarray(pooled, dtype=np.float64), corrections


def fit(
    reference: PhotoSource,
    inputs: PhotoSource,
    name: str = "look",
    transport_strength: float = DEFAULT_TRANSPORT_STRENGTH,
    portrait: bool = False,
    seed: int = io.DEFAULT_SEED,
) -> FitResult:
    """Fit a look from reference photos and your photos.

    ``reference`` and ``inputs`` are each a photo, a folder of photos, or a
    list of photos. The photos themselves are never modified.
    """
    if not 0.0 <= transport_strength <= 1.0:
        raise ValueError(
            f"The transport strength must be from 0 to 1, got {transport_strength}."
        )
    refs, per_ref = _sample_group(collect_photos(reference), "reference", seed)
    mine, per_input = _sample_group(collect_photos(inputs), "input photos", seed)

    # 1. Neutralize within each group, then pool.
    ref_srgb, ref_corrections = _neutralized(refs)
    in_srgb, in_corrections = _neutralized(mine)
    ref_lab, in_lab = io.srgb_to_oklab(ref_srgb), io.srgb_to_oklab(in_srgb)

    # 2. Tone curve, split toning, then transport for the rest.
    curve = tone.fit_tone_curve(in_lab[:, 0], ref_lab[:, 0])

    def tone_and_toning(lab: FloatArray, tint: toning.SplitToning | None) -> FloatArray:
        out = lab.copy()
        out[..., 0] = tone.apply_tone_curve(lab[..., 0], curve)
        return out if tint is None else toning.apply_split_toning(out, tint)

    split = toning.fit_split_toning(tone_and_toning(in_lab, None), ref_lab)
    fitted = tone_and_toning(in_lab, split)
    target_lab = transport.sliced_transport(
        fitted, ref_lab, strength=transport_strength, seed=seed
    )

    # The prior: what colors no photo contains fall back to.
    grid_srgb = identity_table(LUT_SIZE).reshape(-1, 3)
    grid_lab = io.srgb_to_oklab(grid_srgb)
    prior_lab = tone_and_toning(grid_lab, split)

    # 3. Portrait mode: cap skin hue rotation.
    if portrait:
        target_lab = skin.limit_skin_hue(in_lab, target_lab, skin.skin_mask(in_srgb))
        prior_lab = skin.limit_skin_hue(grid_lab, prior_lab, skin.skin_mask(grid_srgb))

    # 4. Bake.
    prior = np.clip(io.oklab_to_srgb(prior_lab), 0.0, 1.0)
    target = np.clip(io.oklab_to_srgb(target_lab), 0.0, 1.0)
    baked = bake_lut(
        in_srgb,
        target,
        prior=prior.reshape(LUT_SIZE, LUT_SIZE, LUT_SIZE, 3),
        title=name,
    )

    drift = skin.measure_skin_drift(in_srgb, apply_lut(in_srgb, baked.cube))
    photos = [
        Photo.from_estimate(s.path, "reference", s.source, s.estimate, c)
        for s, c in zip(refs, ref_corrections, strict=True)
    ] + [
        Photo.from_estimate(s.path, "input", s.source, s.estimate, c)
        for s, c in zip(mine, in_corrections, strict=True)
    ]
    look = Look(
        name=name,
        seed=seed,
        settings={
            "lut_size": LUT_SIZE,
            "samples_per_reference": per_ref,
            "samples_per_input": per_input,
            "white_balance_blend": neutralize.BLEND,
            "exposure_strength": neutralize.EXPOSURE_STRENGTH,
            "max_exposure_stops": neutralize.MAX_EXPOSURE_STOPS,
            "transport_strength": transport_strength,
            "transport_iterations": transport.ITERATIONS,
            "smoothness": SMOOTHNESS,
            "prior_pull": PRIOR_PULL,
            "portrait": portrait,
            "skin_max_degrees": skin.MAX_DRIFT_DEGREES,
        },
        photos=photos,
        tone_curve=curve.tolist(),
        split_toning=split,
        metrics={
            "lut_total_variation": baked.total_variation,
            "lut_coverage": baked.coverage,
            "lut_gray_monotonic": float(baked.gray_monotonic),
            "skin_fraction": drift.fraction,
            "skin_hue_drift_mean": drift.mean_abs,
            "skin_hue_drift_p95": drift.p95_abs,
        },
    )
    look.validate()
    return FitResult(look=look, cube=baked.cube, bake=baked)
