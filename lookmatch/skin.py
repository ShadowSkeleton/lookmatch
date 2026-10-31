"""Rule-based skin mask and skin hue drift constraint.

Strong looks often push skin toward green, gray or orange, and people notice
skin hue more than any other color. lookmatch finds skin-colored pixels with
a fixed color rule (no AI model), measures how far a look rotates their hue,
and can cap that rotation.

Skin mask: a pixel counts as skin when its YCbCr chroma falls in the box
77 <= Cb <= 127 and 133 <= Cr <= 173 (Chai and Ngan 1999), using 8-bit
ITU-R BT.601 YCbCr computed from sRGB-encoded values. lookmatch also requires
40 <= Y <= 235, skipping near-black and near-white pixels, whose color is
mostly noise or clipping.

Known limitation: the rule looks only at color, so skin-colored objects
(sand, wood, terracotta, orange fabric) also count as skin. On desert
landscapes it marked 40-68% of the pixels as skin. That is why
limit_skin_hue is only used in portrait mode (--portrait); measure_skin_drift
runs on every look for the report.

Hue drift: the change in OKLCh hue, in degrees, wrapped to (-180, 180].
Pixels with OKLCh chroma below 0.02 are skipped because their hue is
unstable: a tiny change can swing it by many degrees.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from lookmatch import io

FloatArray = npt.NDArray[np.floating[Any]]
BoolArray = npt.NDArray[np.bool_]

CB_RANGE = (77.0, 127.0)  # Chai and Ngan 1999
CR_RANGE = (133.0, 173.0)  # Chai and Ngan 1999
Y_RANGE = (40.0, 235.0)  # lookmatch: skip near-black and near-white
MIN_CHROMA = 0.02  # OKLCh chroma below which hue is too unstable to judge
MAX_DRIFT_DEGREES = 6.0  # default limit from the project brief


@dataclass(frozen=True)
class SkinDrift:
    """How much a look rotates skin hue."""

    count: int  # skin pixels measured
    fraction: float  # share of all pixels that are measured skin
    mean_abs: float  # average absolute hue change, degrees
    p95_abs: float  # 95th percentile absolute hue change, degrees
    mean_signed: float  # average signed change (+ toward yellow, - toward magenta)


def _ycbcr(srgb: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Return 8-bit studio-range YCbCr (ITU-R BT.601) from sRGB in [0, 1]."""
    m = np.array(
        [
            [65.481, 128.553, 24.966],
            [-37.797, -74.203, 112.0],
            [112.0, -93.786, -18.214],
        ]
    )
    return np.asarray(srgb @ m.T + np.array([16.0, 128.0, 128.0]), dtype=np.float64)


def skin_mask(srgb: npt.ArrayLike) -> BoolArray:
    """Return True for skin-colored pixels. Output shape is input shape[:-1]."""
    v = np.asarray(srgb, dtype=np.float64)
    if v.ndim == 0 or v.shape[-1] != 3:
        raise ValueError(f"Expected colors with 3 color channels, got shape {v.shape}.")
    y, cb, cr = np.moveaxis(_ycbcr(np.clip(v, 0.0, 1.0)), -1, 0)
    inside = (
        (cb >= CB_RANGE[0])
        & (cb <= CB_RANGE[1])
        & (cr >= CR_RANGE[0])
        & (cr <= CR_RANGE[1])
        & (y >= Y_RANGE[0])
        & (y <= Y_RANGE[1])
    )
    return np.asarray(inside, dtype=np.bool_)


def hue_drift(before_lab: npt.ArrayLike, after_lab: npt.ArrayLike) -> FloatArray:
    """Return the OKLCh hue change from before to after, degrees in (-180, 180]."""
    h0 = io.oklab_to_oklch(before_lab)[..., 2]
    h1 = io.oklab_to_oklch(after_lab)[..., 2]
    d = (h1 - h0) % 360.0
    return np.where(d > 180.0, d - 360.0, d)


def measure_skin_drift(
    before_srgb: npt.ArrayLike, after_srgb: npt.ArrayLike
) -> SkinDrift:
    """Measure skin hue drift between the same pixels before and after a look.

    Skin is found in the before pixels. Both inputs are sRGB-encoded colors
    of the same shape.
    """
    before = np.asarray(before_srgb, dtype=np.float64).reshape(-1, 3)
    after = np.asarray(after_srgb, dtype=np.float64).reshape(-1, 3)
    if before.shape != after.shape:
        raise ValueError("The before and after pixels must have the same shape.")
    lab0, lab1 = io.srgb_to_oklab(before), io.srgb_to_oklab(after)
    chroma0 = io.oklab_to_oklch(lab0)[:, 1]
    measured = skin_mask(before) & (chroma0 >= MIN_CHROMA)
    count = int(measured.sum())
    if count == 0:
        return SkinDrift(0, 0.0, 0.0, 0.0, 0.0)
    d = hue_drift(lab0[measured], lab1[measured])
    return SkinDrift(
        count=count,
        fraction=count / before.shape[0],
        mean_abs=float(np.mean(np.abs(d))),
        p95_abs=float(np.percentile(np.abs(d), 95)),
        mean_signed=float(np.mean(d)),
    )


def limit_skin_hue(
    before_lab: npt.ArrayLike,
    after_lab: npt.ArrayLike,
    mask: npt.ArrayLike,
    max_degrees: float = MAX_DRIFT_DEGREES,
) -> npt.NDArray[np.float64]:
    """Cap the hue rotation of skin pixels at max_degrees.

    For masked pixels whose hue moved more than max_degrees, the hue is set
    to the before hue plus max_degrees in the same direction. Their new
    lightness and chroma are kept, so the look's brightness and saturation
    still apply to skin. All other pixels are returned unchanged.
    """
    lab0 = np.asarray(before_lab, dtype=np.float64)
    out = np.array(after_lab, dtype=np.float64)
    m = np.asarray(mask, dtype=bool)
    lch0, lch1 = io.oklab_to_oklch(lab0), io.oklab_to_oklch(out)
    d = hue_drift(lab0, out)
    fix = m & (lch0[..., 1] >= MIN_CHROMA) & (lch1[..., 1] >= MIN_CHROMA)
    fix &= np.abs(d) > max_degrees
    if np.any(fix):
        capped = lch1[fix].copy()
        capped[:, 2] = (lch0[fix][:, 2] + np.sign(d[fix]) * max_degrees) % 360.0
        out[fix] = io.oklch_to_oklab(capped)
    return out
