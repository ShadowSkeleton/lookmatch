"""Split toning fit for shadows, midtones, and highlights.

Split toning is the color tint a look adds at each lightness, like the three
Color Grading wheels in Lightroom: for example teal shadows and warm
highlights. lookmatch models it as an OKLab (a, b) offset that changes
smoothly with lightness L:

    offset(L) = w_s(L) * shadows + w_m(L) * midtones + w_h(L) * highlights

with the zone weights w_s = (1 - L)^2, w_m = 2 L (1 - L), w_h = L^2 (the
quadratic Bernstein basis). They are smooth, never negative, add up to 1 at
every L, and peak at black, middle gray and white.

Fitting: the input and reference pixels are each grouped into 32 lightness
bins, and the average (a, b) is taken per bin on each side. The difference
between the two sides, bin by bin, is the tint at that lightness. The three
zone offsets are the weighted least squares fit of those differences, with
bins weighted by how many pixels support them and a small ridge term that
keeps a zone with no pixels near zero instead of guessing.

The input's lightness should already have the tone curve applied, so each
bin compares pixels that end up equally bright.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.floating[Any]]
Offset = tuple[float, float]

ZONES = ("shadows", "midtones", "highlights")
BINS = 32
MIN_BIN_PIXELS = 20  # a bin needs this many pixels on both sides to count
RIDGE = 1e-3  # relative strength of the pull toward zero


@dataclass(frozen=True)
class SplitToning:
    """OKLab (a, b) offsets for shadows, midtones and highlights."""

    shadows: Offset = (0.0, 0.0)
    midtones: Offset = (0.0, 0.0)
    highlights: Offset = (0.0, 0.0)

    def as_array(self) -> npt.NDArray[np.float64]:
        """Return the offsets as a (3, 2) array: zones by (a, b)."""
        return np.array(
            [self.shadows, self.midtones, self.highlights], dtype=np.float64
        )

    def hue_chroma(self, zone: str) -> tuple[float, float]:
        """Return a zone's tint as OKLCh hue (degrees, 0 to 360) and chroma."""
        a, b = getattr(self, zone)
        return float(np.degrees(np.arctan2(b, a)) % 360.0), float(np.hypot(a, b))


def zone_weights(lightness: npt.ArrayLike) -> npt.NDArray[np.float64]:
    """Return shadow, midtone and highlight weights, shape (..., 3)."""
    t = np.clip(np.asarray(lightness, dtype=np.float64), 0.0, 1.0)
    return np.stack([(1 - t) ** 2, 2 * t * (1 - t), t**2], axis=-1)


def _check(lab: npt.ArrayLike, what: str) -> npt.NDArray[np.float64]:
    v = np.asarray(lab, dtype=np.float64)
    if v.ndim == 0 or v.shape[-1] != 3:
        raise ValueError(
            f"The {what} colors need 3 color channels (OKLab L, a, b), got shape "
            f"{v.shape}."
        )
    v = v.reshape(-1, 3)
    if v.shape[0] == 0:
        raise ValueError(f"The {what} photos gave no pixels to measure.")
    if not np.all(np.isfinite(v)):
        raise ValueError(f"The {what} colors contain NaN or infinite values.")
    return v


def _bin_means(lab: npt.NDArray[np.float64]) -> tuple[npt.NDArray[np.float64], ...]:
    """Pixel count and mean (a, b) in each lightness bin."""
    idx = np.clip((lab[:, 0] * BINS).astype(np.intp), 0, BINS - 1)
    count = np.bincount(idx, minlength=BINS).astype(np.float64)
    safe = np.maximum(count, 1)
    mean_a = np.bincount(idx, weights=lab[:, 1], minlength=BINS) / safe
    mean_b = np.bincount(idx, weights=lab[:, 2], minlength=BINS) / safe
    return count, mean_a, mean_b


def fit_split_toning(
    input_lab: npt.ArrayLike, reference_lab: npt.ArrayLike
) -> SplitToning:
    """Fit split toning from pooled OKLab samples of both sides."""
    n_in, a_in, b_in = _bin_means(_check(input_lab, "input"))
    n_ref, a_ref, b_ref = _bin_means(_check(reference_lab, "reference"))

    usable = (n_in >= MIN_BIN_PIXELS) & (n_ref >= MIN_BIN_PIXELS)
    if not np.any(usable):
        return SplitToning()

    # Weight each bin like the inverse variance of a difference of two means,
    # as fractions so the total pixel count doesn't matter.
    f_in, f_ref = n_in / n_in.sum(), n_ref / n_ref.sum()
    weight = np.where(usable, f_in * f_ref / np.maximum(f_in + f_ref, 1e-12), 0.0)

    centers = (np.arange(BINS) + 0.5) / BINS
    basis = zone_weights(centers)  # (BINS, 3)
    diff = np.stack([a_ref - a_in, b_ref - b_in], axis=-1)  # (BINS, 2)

    # Weighted least squares with a small ridge: (X'WX + lambda I) theta = X'W d
    xtw = basis.T * weight
    lam = RIDGE * weight.sum()
    theta = np.linalg.solve(xtw @ basis + lam * np.eye(3), xtw @ diff)  # (3, 2)

    s, m, h = (tuple(float(v) for v in row) for row in theta)
    return SplitToning(
        shadows=(s[0], s[1]), midtones=(m[0], m[1]), highlights=(h[0], h[1])
    )


def apply_split_toning(lab: npt.ArrayLike, toning: SplitToning) -> FloatArray:
    """Add the split toning offsets to OKLab colors. Lightness is unchanged."""
    v = np.asarray(lab, dtype=np.float64)
    if v.ndim == 0 or v.shape[-1] != 3:
        raise ValueError(f"Expected OKLab colors with 3 channels, got shape {v.shape}.")
    out = v.copy()
    out[..., 1:] += zone_weights(v[..., 0]) @ toning.as_array()
    return out
