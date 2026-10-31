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

Averages assume both sides show similar scenes: red rock in the references
reads as an orange tint. fit_neutral_toning() is the robust alternative for
other scenes; it compares the most common colors instead and shrinks a tint
the reference photos disagree on. The pipeline blends the two by how alike
the scenes are.
"""

from collections.abc import Sequence
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
MODE_RADIUS = 0.02  # OKLab (a, b) window for finding the most common color
MODE_ITERATIONS = 20
CAUTION = 2.0  # how strongly disagreement between references shrinks a tint


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

    diff = _fit_offsets(
        n_in, np.stack([a_in, b_in], axis=-1), n_ref, np.stack([a_ref, b_ref], axis=-1)
    )
    return _from_array(diff)


def apply_split_toning(lab: npt.ArrayLike, toning: SplitToning) -> FloatArray:
    """Add the split toning offsets to OKLab colors. Lightness is unchanged."""
    v = np.asarray(lab, dtype=np.float64)
    if v.ndim == 0 or v.shape[-1] != 3:
        raise ValueError(f"Expected OKLab colors with 3 channels, got shape {v.shape}.")
    out = v.copy()
    out[..., 1:] += zone_weights(v[..., 0]) @ toning.as_array()
    return out


def _mode_ab(ab: npt.NDArray[np.float64], radius: float) -> npt.NDArray[np.float64]:
    """Find the most common (a, b) color by mean shift from the median.

    Mean shift (Fukunaga and Hostetler 1975) with a flat window moves to the
    mean of the colors within ``radius`` until it settles on the densest
    point. It moves exactly with a tint added to every pixel, so the
    difference between two modes measures a tint without being pulled by a
    few large colored objects the way a mean is.
    """
    center = np.median(ab, axis=0)
    for _ in range(MODE_ITERATIONS):
        near = np.sum((ab - center) ** 2, axis=1) < radius**2
        if np.count_nonzero(near) < MIN_BIN_PIXELS:
            break
        new = ab[near].mean(axis=0)
        if np.allclose(new, center, atol=1e-6):
            break
        center = new
    return np.asarray(center, dtype=np.float64)


def _bin_modes(
    lab: npt.NDArray[np.float64], radius: float
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Pixel count and most common (a, b) in each lightness bin."""
    idx = np.clip((lab[:, 0] * BINS).astype(np.intp), 0, BINS - 1)
    count = np.bincount(idx, minlength=BINS).astype(np.float64)
    modes = np.zeros((BINS, 2))
    for b in np.flatnonzero(count >= MIN_BIN_PIXELS):
        modes[b] = _mode_ab(lab[idx == b, 1:], radius)
    return count, modes


def _fit_offsets(
    n_in: npt.NDArray[np.float64],
    c_in: npt.NDArray[np.float64],
    n_ref: npt.NDArray[np.float64],
    c_ref: npt.NDArray[np.float64],
) -> npt.NDArray[np.float64]:
    """Zone offsets (3, 2) from per-bin colors of both sides (see module doc)."""
    usable = (n_in >= MIN_BIN_PIXELS) & (n_ref >= MIN_BIN_PIXELS)
    if not np.any(usable):
        return np.zeros((3, 2))
    # Weight each bin like the inverse variance of a difference of two means,
    # as fractions so the total pixel count doesn't matter.
    f_in, f_ref = n_in / n_in.sum(), n_ref / n_ref.sum()
    weight = np.where(usable, f_in * f_ref / np.maximum(f_in + f_ref, 1e-12), 0.0)
    basis = zone_weights((np.arange(BINS) + 0.5) / BINS)
    xtw = basis.T * weight
    # Weighted least squares with a small ridge: (X'WX + lambda I) theta = X'W d
    lam = RIDGE * weight.sum()
    out = np.linalg.solve(xtw @ basis + lam * np.eye(3), xtw @ (c_ref - c_in))
    return np.asarray(out, dtype=np.float64)


def _from_array(theta: npt.NDArray[np.float64]) -> SplitToning:
    s, m, h = (tuple(float(v) for v in row) for row in theta)
    return SplitToning(
        shadows=(s[0], s[1]), midtones=(m[0], m[1]), highlights=(h[0], h[1])
    )


@dataclass(frozen=True)
class NeutralFit:
    """Result of fit_neutral_toning."""

    toning: SplitToning
    kept: npt.NDArray[np.float64]  # factor (0 to 1) kept in each zone
    # How much the reference photos disagree: the root mean square distance
    # (OKLab a, b) of each photo's own tint from the average tint, over all
    # zones. 0 with a single reference photo.
    spread: float


def fit_neutral_toning(
    input_lab: npt.ArrayLike,
    reference_labs: Sequence[npt.ArrayLike],
    radius: float = MODE_RADIUS,
    caution: float = CAUTION,
) -> NeutralFit:
    """Fit split toning that holds up when the scenes differ.

    Two changes from fit_split_toning make it robust to scene content:

    1. Each lightness bin is summarized by its most common color (the mode)
       instead of the average. In most photos the most common color is a
       near-neutral (sky, walls, road, shade), so the modes measure how the
       look tints neutrals, while the average is pulled by whatever large
       colored object the scene contains.
    2. The tint is also fitted from each reference photo alone. A look tints
       every photo the same way, so the photos agree; content differs from
       photo to photo, so they scatter. Each zone's tint is shrunk toward
       zero by signal / (signal + caution * noise), where signal is the
       squared pooled tint and noise is the squared standard error of the
       per-photo tints (an empirical Bayes shrinkage, Efron and Morris
       1975). A single reference photo can't show agreement, so its tint is
       kept unshrunk.

    ``reference_labs`` holds the OKLab samples of each reference photo.
    """
    refs = [_check(r, "reference") for r in reference_labs]
    if not refs:
        raise ValueError("Need at least one reference photo to fit split toning.")
    n_in, m_in = _bin_modes(_check(input_lab, "input"), radius)
    n_ref, m_ref = _bin_modes(np.vstack(refs), radius)
    pooled = _fit_offsets(n_in, m_in, n_ref, m_ref)
    if len(refs) < 2:
        return NeutralFit(_from_array(pooled), np.ones(3), 0.0)

    per_photo = np.stack(
        [_fit_offsets(n_in, m_in, *_bin_modes(r, radius)) for r in refs]
    )
    variance = per_photo.var(axis=0, ddof=1).sum(axis=1)  # per zone
    noise = variance / len(refs)  # squared standard error of the mean
    signal = np.sum(pooled**2, axis=1)
    keep = signal / np.maximum(signal + caution * noise, 1e-30)
    spread = float(np.sqrt(variance.mean()))
    return NeutralFit(_from_array(pooled * keep[:, None]), keep, spread)


def blend_toning(safe: SplitToning, full: SplitToning, weight: float) -> SplitToning:
    """Blend two toning fits: weight 0 gives ``safe``, 1 gives ``full``."""
    a = safe.as_array()
    return _from_array(a + float(weight) * (full.as_array() - a))
