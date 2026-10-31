"""White balance and exposure normalization.

Each photo's light is estimated from its pixels:

- White balance: the color of the light, as a blend of two classic estimates.
  Gray world (Buchsbaum 1980) assumes the scene averages to gray, so the
  average color is the light's color. White patch (Land and McCann 1971)
  assumes the brightest surfaces are white, so their color is the light's
  color. Each fails on different scenes (a red canyon fools gray world; a
  scene with no white object fools white patch), so they are blended.
- Exposure: the median luminance, which a few very bright or dark pixels
  can't move.

Photos are then corrected *relative to their group* (all reference photos,
or all of the user's photos), not to absolute gray. Each photo moves to the
group's shared average light and exposure. This removes the differences
between photos (one shot in shade, one at sunset) but keeps what they share,
so a reference look's overall warmth is kept as part of the look. A single
photo is left unchanged.

Corrections are diagonal gains in linear sRGB (the von Kries model).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from lookmatch import io

FloatArray = npt.NDArray[np.floating[Any]]

# Rec. 709 / sRGB luminance weights for linear RGB (ITU-R BT.709).
LUMA = np.array([0.2126, 0.7152, 0.0722])

BLEND = 0.5  # weight of gray world vs white patch (1 = only gray world)
BRIGHTEST = 0.01  # white patch: average of the brightest 1% of usable pixels
CLIPPED = 0.95  # linear value at which a channel counts as clipped
NEAR_BLACK = 0.002  # luminance below which pixels are mostly noise
MIN_PIXELS = 100  # fewer usable pixels than this: no reliable estimate
MAX_CAST = 4.0  # strongest channel / weakest channel allowed in an estimate

# Median luminance can't tell a dark scene (a slot canyon) from an
# underexposed one. Correcting fully pushed a correctly exposed canyon photo
# +2.3 stops and a bright sky photo -1.8 stops, so exposure is only corrected
# halfway (in stops) and never by more than one stop.
EXPOSURE_STRENGTH = 0.5
MAX_EXPOSURE_STOPS = 1.0


@dataclass(frozen=True)
class Estimate:
    """The measured light of one photo."""

    illuminant: npt.NDArray[np.float64]  # linear RGB of the light, luminance 1
    median_luminance: float  # median linear luminance of the photo
    reliable: bool  # False if the photo had too little usable information


@dataclass(frozen=True)
class Correction:
    """Gains that move one photo to its group's shared light and exposure."""

    white_balance: npt.NDArray[np.float64]  # per-channel gains, luminance 1
    exposure: float  # overall gain


def _unit_luminance(rgb: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    return rgb / float(rgb @ LUMA)


def estimate(srgb: npt.ArrayLike, blend: float = BLEND) -> Estimate:
    """Measure the light color and exposure of a photo from sRGB pixels.

    ``srgb`` is any array of sRGB-encoded colors with 3 channels on the last
    axis, usually the output of io.sample_pixels. ``blend`` weights gray
    world against white patch, geometrically.
    """
    linear = io.srgb_to_linear(np.asarray(srgb, dtype=np.float64)).reshape(-1, 3)
    luminance = linear @ LUMA
    median = float(np.median(luminance)) if luminance.size else 0.0

    usable = (luminance > NEAR_BLACK) & (linear.max(axis=1) < CLIPPED)
    pixels = linear[usable]
    if pixels.shape[0] < MIN_PIXELS or np.any(pixels.mean(axis=0) <= 0):
        return Estimate(np.ones(3), median, reliable=False)

    gray_world = _unit_luminance(pixels.mean(axis=0))
    n_bright = max(MIN_PIXELS // 10, int(round(pixels.shape[0] * BRIGHTEST)))
    brightest = np.argsort(pixels @ LUMA)[-n_bright:]
    white_patch = _unit_luminance(pixels[brightest].mean(axis=0))
    if np.any(white_patch <= 0):
        white_patch = gray_world

    illuminant = _unit_luminance(gray_world**blend * white_patch ** (1 - blend))

    # A cast stronger than MAX_CAST is almost surely scene color, not light.
    floor = illuminant.max() / MAX_CAST
    reliable = bool(np.all(illuminant >= floor))
    if not reliable:
        illuminant = _unit_luminance(np.maximum(illuminant, floor))
    return Estimate(illuminant, median, reliable)


def group_corrections(
    estimates: Sequence[Estimate],
    exposure_strength: float = EXPOSURE_STRENGTH,
    max_exposure_stops: float = MAX_EXPOSURE_STOPS,
) -> list[Correction]:
    """Return the correction that moves each photo to the group's average.

    The shared light is the geometric mean of the reliable photos' lights,
    and the shared exposure is the geometric mean of their median
    luminances. White balance is corrected fully; exposure by
    ``exposure_strength`` of the difference in stops, capped at
    ``max_exposure_stops``. Unreliable photos get no correction and don't
    count.
    """
    good = [e for e in estimates if e.reliable and e.median_luminance > 0]
    if not good:
        return [Correction(np.ones(3), 1.0) for _ in estimates]

    shared_light = np.exp(np.mean([np.log(e.illuminant) for e in good], axis=0))
    shared_light = _unit_luminance(shared_light)
    shared_exposure = float(np.exp(np.mean([np.log(e.median_luminance) for e in good])))

    corrections = []
    for e in estimates:
        if e.reliable and e.median_luminance > 0:
            gains = _unit_luminance(shared_light / e.illuminant)
            stops = exposure_strength * np.log2(shared_exposure / e.median_luminance)
            stops = float(np.clip(stops, -max_exposure_stops, max_exposure_stops))
            corrections.append(Correction(gains, 2.0**stops))
        else:
            corrections.append(Correction(np.ones(3), 1.0))
    return corrections


def apply_correction(srgb: npt.ArrayLike, correction: Correction) -> FloatArray:
    """Apply a correction to sRGB colors, returning sRGB colors.

    The gains are applied in linear light. The result is not clipped: values
    above 1 are kept so later fitting steps see the true colors.
    """
    v = np.asarray(srgb)
    linear = io.srgb_to_linear(v)
    gains = (correction.white_balance * correction.exposure).astype(linear.dtype)
    return io.linear_to_srgb(linear * gains)
