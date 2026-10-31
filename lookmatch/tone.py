"""Monotonic tone curve fitting on OKLab lightness.

The tone curve answers "how does the look map shadows, midtones and
highlights?" It is fitted in three steps:

1. Histogram matching. The pooled lightness of the user's photos and of the
   reference photos are each summarized by 1000 quantiles. Matching quantile
   to quantile gives pairs (input lightness, reference lightness): the
   darkest 1% of your photos maps to the darkest 1% of the reference, and so
   on. Photos don't need to show the same scene, only similar content.
2. Isotonic regression (Barlow et al. 1972). Ties (for example many clipped
   white pixels) can make the pairs disagree; isotonic regression finds the
   closest curve that never goes down, so a brighter input never comes out
   darker.
3. PCHIP interpolation (Fritsch and Carlson 1980). The pairs are averaged
   into about 50 knots and joined by a smooth curve that keeps their shape
   and never overshoots, then sampled at 256 points.

Outside the lightness range seen in the user's photos, the curve continues
at slope 1 (no extra contrast) from its ends, clipped to [0, 1].
"""

from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.interpolate import PchipInterpolator
from scipy.optimize import isotonic_regression

FloatArray = npt.NDArray[np.floating[Any]]

SAMPLES = 256
GRID = np.linspace(0.0, 1.0, SAMPLES)  # input lightness of each curve sample
QUANTILES = 1000
KNOT_GROUP = 20  # quantile pairs averaged into one knot (about 50 knots)


def _lightness(values: npt.ArrayLike, what: str) -> npt.NDArray[np.float64]:
    v = np.asarray(values, dtype=np.float64).ravel()
    if v.size == 0:
        raise ValueError(f"The {what} photos gave no pixels to measure.")
    if not np.all(np.isfinite(v)):
        raise ValueError(f"The {what} lightness contains NaN or infinite values.")
    return np.clip(v, 0.0, 1.0)  # the LUT works on display values, 0 to 1


def fit_tone_curve(
    input_lightness: npt.ArrayLike, reference_lightness: npt.ArrayLike
) -> npt.NDArray[np.float64]:
    """Fit the tone curve from pooled OKLab L samples.

    Returns 256 output lightness values, one per entry of GRID: never going
    down, inside [0, 1].
    """
    x_all = _lightness(input_lightness, "input")
    y_all = _lightness(reference_lightness, "reference")

    # 1. Histogram matching by quantiles.
    q = (np.arange(QUANTILES) + 0.5) / QUANTILES
    xq = np.quantile(x_all, q)
    yq = np.quantile(y_all, q)

    # 2. Merge equal inputs, then the closest never-decreasing fit.
    x, inverse, counts = np.unique(xq, return_inverse=True, return_counts=True)
    y = np.bincount(inverse, weights=yq) / counts
    y = isotonic_regression(y, weights=counts.astype(np.float64)).x

    # 3. Average into knots (keeping both ends exact) and join with PCHIP.
    knots_x, knots_y = _knots(x, y, counts)
    if knots_x.size == 1:  # every input pixel had the same lightness
        fitted = np.full_like(GRID, knots_y[0])
    else:
        fitted = PchipInterpolator(knots_x, knots_y, extrapolate=False)(GRID)

    # Beyond the data: slope 1 from each end, inside [0, 1].
    x0, y0, x1, y1 = knots_x[0], knots_y[0], knots_x[-1], knots_y[-1]
    fitted = np.where(GRID < x0, y0 - (x0 - GRID), fitted)
    fitted = np.where(GRID > x1, y1 + (GRID - x1), fitted)
    curve = np.clip(fitted, 0.0, 1.0)
    return np.maximum.accumulate(curve)  # remove float rounding wiggles


def _knots(
    x: npt.NDArray[np.float64], y: npt.NDArray[np.float64], w: npt.NDArray[np.int64]
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Weighted means of consecutive groups of points, plus both end points."""
    groups = np.arange(x.size) // KNOT_GROUP
    weight = np.bincount(groups, weights=w)
    gx = np.bincount(groups, weights=w * x) / weight
    gy = np.bincount(groups, weights=w * y) / weight
    kx = np.concatenate([[x[0]], gx, [x[-1]]])
    ky = np.concatenate([[y[0]], gy, [y[-1]]])
    # PCHIP needs strictly increasing x; merge any repeats.
    kx, inverse = np.unique(kx, return_inverse=True)
    ky = np.bincount(inverse, weights=ky) / np.bincount(inverse)
    return kx, np.maximum.accumulate(ky)


def apply_tone_curve(lightness: npt.ArrayLike, curve: npt.ArrayLike) -> FloatArray:
    """Map lightness through a 256-sample curve, interpolating linearly."""
    v = np.asarray(lightness, dtype=np.float64)
    return np.interp(v, GRID, np.asarray(curve, dtype=np.float64))
