"""The full pipeline: reference photos and your photos in, a fitted look out.

fit() runs every step in order (see docs/method.md for each one):

0. Load each photo and sample its pixels. Photos are loaded one at a time
   and dropped after sampling, so memory stays low with many photos.
1. Neutralize: measure each photo's light and exposure, and move each photo
   toward its own group's average (references as one group, yours as the
   other).
2. Fit the safe part of the look, which holds up even when the references
   show other scenes: black and white points, and the tint of the most
   common colors, kept only as far as the reference photos agree on it.
3. Measure how alike the two sets of scenes are (see scenes.py): are the
   references graded copies of your photos, and how close are the colors
   after the safe fit? The full fit (whole tone
   curve, average tint, sliced optimal transport) is blended in only as far
   as they are, because on other scenes it copies their content as if it
   were the look.
4. In portrait mode only, cap how far skin hue may rotate.
5. Bake the 33-point LUT, falling back to tone curve plus split toning for
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

from lookmatch import io, metrics, neutralize, scenes, skin, tone, toning, transport
from lookmatch.apply import apply_lut
from lookmatch.bake import LUT_SIZE, PRIOR_PULL, SMOOTHNESS, BakeResult, bake_lut
from lookmatch.export.cube import Cube, identity_table
from lookmatch.look import Look, Photo

# Transport strength when the scenes match; it fades out as they differ.
DEFAULT_TRANSPORT_STRENGTH = 1.0
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
    structure: npt.NDArray[np.float64]  # see scenes.structure
    aspect: float


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
        shape = (scenes.structure(image), scenes.aspect(image))
        del image  # keep memory low: only the samples and structure are needed
        source = "raw" if path.suffix.lower() in io.RAW_EXTENSIONS else "rendered"
        sampled.append(
            _Sampled(path, source, pixels, neutralize.estimate(pixels), *shape)
        )
    return sampled, per_photo


def _neutralized(
    group: list[_Sampled],
) -> tuple[list[npt.NDArray[np.float64]], list[neutralize.Correction]]:
    """Each photo's samples moved to the group's shared light and exposure."""
    corrections = neutralize.group_corrections([s.estimate for s in group])
    photos = [
        np.asarray(
            np.clip(neutralize.apply_correction(s.pixels, c), 0.0, 1.0),
            dtype=np.float64,
        )
        for s, c in zip(group, corrections, strict=True)
    ]
    return photos, corrections


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
    ref_photos, ref_corrections = _neutralized(refs)
    in_photos, in_corrections = _neutralized(mine)
    ref_srgb, in_srgb = np.vstack(ref_photos), np.vstack(in_photos)
    ref_lab, in_lab = io.srgb_to_oklab(ref_srgb), io.srgb_to_oklab(in_srgb)
    ref_labs = [io.srgb_to_oklab(p) for p in ref_photos]

    def tone_and_toning(
        lab: FloatArray, curve: FloatArray, tint: toning.SplitToning | None
    ) -> FloatArray:
        out = lab.copy()
        out[..., 0] = tone.apply_tone_curve(lab[..., 0], curve)
        return out if tint is None else toning.apply_split_toning(out, tint)

    # 2. The safe part of the look: black and white points, and the tint of
    # the most common colors, kept only as far as the references agree.
    safe_curve = tone.fit_end_points(in_lab[:, 0], ref_lab[:, 0])
    safe_split, _ = toning.fit_neutral_toning(
        tone_and_toning(in_lab, safe_curve, None), ref_labs
    )

    # 3. How alike are the scenes? The full fit (whole tone curve, average
    # tint, transport) is used only as far as they are: on other scenes it
    # mistakes the difference in content for a look (docs/method.md).
    copied = scenes.copied_fraction(
        [(s.structure, s.aspect) for s in refs],
        [(s.structure, s.aspect) for s in mine],
    )
    distance = metrics.sliced_wasserstein(
        tone_and_toning(in_lab, safe_curve, safe_split), ref_lab, seed=seed
    )
    match = scenes.scene_match(copied, distance)
    curve = tone.blend_curves(
        safe_curve, tone.fit_tone_curve(in_lab[:, 0], ref_lab[:, 0]), match
    )
    toned = tone_and_toning(in_lab, curve, None)
    neutral_split, kept = toning.fit_neutral_toning(toned, ref_labs)
    split = toning.blend_toning(
        neutral_split, toning.fit_split_toning(toned, ref_lab), match
    )
    fitted = tone_and_toning(in_lab, curve, split)
    strength = transport_strength * match
    target_lab = (
        transport.sliced_transport(fitted, ref_lab, strength=strength, seed=seed)
        if strength > 0
        else fitted
    )

    # The prior: what colors no photo contains fall back to.
    grid_srgb = identity_table(LUT_SIZE).reshape(-1, 3)
    grid_lab = io.srgb_to_oklab(grid_srgb)
    prior_lab = tone_and_toning(grid_lab, curve, split)

    # 4. Portrait mode: cap skin hue rotation.
    if portrait:
        target_lab = skin.limit_skin_hue(in_lab, target_lab, skin.skin_mask(in_srgb))
        prior_lab = skin.limit_skin_hue(grid_lab, prior_lab, skin.skin_mask(grid_srgb))

    # 5. Bake.
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
            "scene_scale": scenes.SCENE_SCALE,
            "same_photo_correlation": scenes.SAME_PHOTO,
            "toning_mode_radius": toning.MODE_RADIUS,
            "toning_caution": toning.CAUTION,
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
            "references_copied_from_inputs": copied,
            "scene_distance": distance,
            "scene_match": match,
            "transport_strength_used": strength,
            **{
                f"toning_kept_{z}": float(k)
                for z, k in zip(toning.ZONES, kept, strict=True)
            },
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
