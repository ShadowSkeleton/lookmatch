"""Quality and artifact metrics for a fitted look.

ΔE 2000 (CIEDE2000) is the standard measure of how different two colors look
to people: below about 1 is invisible, 2 to 3 is barely noticeable side by
side. It is computed with colour-science, from sRGB through CIE XYZ to
CIELAB under D65, following Sharma, Wu and Dalal (2005).

The other metrics:

- Sliced Wasserstein distance (OKLab): how different two sets of colors are
  as a whole. Used to tell how alike two sets of scenes are, and how close
  your photos' colors come to the references' after the look.
- Lightness histogram distance: the same idea for brightness alone, the
  1-dimensional Wasserstein (earth mover's) distance between the OKLab L
  values of two sets of pixels.
- SSIM on lightness (Wang et al. 2004): whether applying the look damaged
  the picture (banding, posterization, noise). A LUT that only changes
  colors smoothly keeps SSIM near 1.
- Skin hue drift and LUT smoothness live next to the code that uses them
  (skin.measure_skin_drift and bake.total_variation).
"""

from typing import Any

import colour
import numpy as np
import numpy.typing as npt
from scipy.stats import wasserstein_distance
from skimage.metrics import structural_similarity

from lookmatch import io

FloatArray = npt.NDArray[np.floating[Any]]


def delta_e_2000_lab(lab1: npt.ArrayLike, lab2: npt.ArrayLike) -> FloatArray:
    """Return CIEDE2000 between two arrays of CIELAB colors."""
    d = colour.delta_E(
        np.asarray(lab1, dtype=np.float64),
        np.asarray(lab2, dtype=np.float64),
        method="CIE 2000",
    )
    return np.asarray(d, dtype=np.float64)


def _srgb_to_lab(srgb: npt.ArrayLike) -> npt.NDArray[np.float64]:
    v = np.clip(np.asarray(srgb, dtype=np.float64), 0.0, 1.0)
    xyz = colour.sRGB_to_XYZ(v)
    return np.asarray(colour.XYZ_to_Lab(xyz), dtype=np.float64)


def delta_e_2000(srgb1: npt.ArrayLike, srgb2: npt.ArrayLike) -> FloatArray:
    """Return CIEDE2000 between two arrays of sRGB colors, per pixel.

    Output shape is the input shape without the last (color) axis.
    """
    return delta_e_2000_lab(_srgb_to_lab(srgb1), _srgb_to_lab(srgb2))


SW_DIRECTIONS = 64
SW_QUANTILES = np.linspace(0.005, 0.995, 199)
SW_MAX_COLORS = 40_000  # per set; a fixed random subset beyond this


def sliced_wasserstein(
    colors1: npt.ArrayLike,
    colors2: npt.ArrayLike,
    directions: int = SW_DIRECTIONS,
    seed: int = 0,
) -> float:
    """Return the sliced Wasserstein distance between two sets of colors.

    Both sets are projected onto the same random directions; on each line,
    the distance is the root mean square gap between matching quantiles
    (the 2-Wasserstein distance in one dimension). The result is the root
    mean square over directions (Rabin et al. 2011), in the units of the
    colors (OKLab for lookmatch). 0 means the two sets have the same color
    distribution. The directions come from a fixed seed, so it is
    repeatable.
    """
    a = np.asarray(colors1, dtype=np.float64).reshape(-1, 3)
    b = np.asarray(colors2, dtype=np.float64).reshape(-1, 3)
    if a.shape[0] == 0 or b.shape[0] == 0:
        raise ValueError("Both color sets need at least one color.")
    rng = np.random.default_rng(seed)
    d = rng.normal(size=(directions, 3))
    a, b = _subset(a, rng), _subset(b, rng)
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    qa, qb = _quantiles(d @ a.T), _quantiles(d @ b.T)
    return float(np.sqrt(np.mean((qa - qb) ** 2)))


def _subset(
    colors: npt.NDArray[np.float64], rng: np.random.Generator
) -> npt.NDArray[np.float64]:
    if colors.shape[0] <= SW_MAX_COLORS:
        return colors
    return colors[rng.choice(colors.shape[0], SW_MAX_COLORS, replace=False)]


def _quantiles(values: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Return SW_QUANTILES of each row, like np.quantile but much faster.

    One sort per row, then linear interpolation between neighbors (numpy's
    default method), instead of one partial sort per quantile.
    """
    ordered = np.sort(values, axis=1)
    position = SW_QUANTILES * (ordered.shape[1] - 1)
    low = np.floor(position).astype(np.intp)
    high = np.minimum(low + 1, ordered.shape[1] - 1)
    weight = position - low
    return np.asarray(
        ordered[:, low] * (1.0 - weight) + ordered[:, high] * weight,
        dtype=np.float64,
    )


def lightness_distance(lab1: npt.ArrayLike, lab2: npt.ArrayLike) -> float:
    """Return the earth mover's distance between two sets of OKLab lightness.

    Both inputs are OKLab colors (..., 3); only L is compared. The result is
    in L units: 0.05 means the brightness histograms are on average 5% of
    the black-to-white range apart.
    """
    a = np.asarray(lab1, dtype=np.float64).reshape(-1, 3)[:, 0]
    b = np.asarray(lab2, dtype=np.float64).reshape(-1, 3)[:, 0]
    if a.size == 0 or b.size == 0:
        raise ValueError("Both color sets need at least one color.")
    return float(wasserstein_distance(a, b))


def ssim_lightness(before_srgb: npt.ArrayLike, after_srgb: npt.ArrayLike) -> float:
    """Return SSIM between the OKLab lightness of two images of equal size.

    1 means the structure is untouched. A smooth tone change lowers it a
    little; banding or noise lowers it a lot. Uses scikit-image's SSIM with
    its default 7-pixel window and a data range of 1.
    """
    before = np.asarray(before_srgb, dtype=np.float64)
    after = np.asarray(after_srgb, dtype=np.float64)
    if before.shape != after.shape or before.ndim != 3 or before.shape[-1] != 3:
        raise ValueError(
            "SSIM needs two RGB images of the same size, got shapes "
            f"{before.shape} and {after.shape}."
        )
    if min(before.shape[:2]) < 7:
        raise ValueError("SSIM needs images at least 7 pixels on each side.")
    l1 = io.srgb_to_oklab(np.clip(before, 0, 1))[..., 0]
    l2 = io.srgb_to_oklab(np.clip(after, 0, 1))[..., 0]
    ssim = structural_similarity(l1, l2, data_range=1.0)  # type: ignore[no-untyped-call]
    return float(ssim)
