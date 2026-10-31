"""Quality and artifact metrics for a fitted look.

ΔE 2000 (CIEDE2000) is the standard measure of how different two colors look
to people: below about 1 is invisible, 2 to 3 is barely noticeable side by
side. It is computed with colour-science, from sRGB through CIE XYZ to
CIELAB under D65, following Sharma, Wu and Dalal (2005).

The sliced Wasserstein distance measures how different two sets of colors
are as a whole; the pipeline uses it to tell how alike two sets of scenes
are. The other metrics in the project brief are added in task 4.1.
"""

from typing import Any

import colour
import numpy as np
import numpy.typing as npt

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
    d = np.random.default_rng(seed).normal(size=(directions, 3))
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    qa = np.quantile(a @ d.T, SW_QUANTILES, axis=0)
    qb = np.quantile(b @ d.T, SW_QUANTILES, axis=0)
    return float(np.sqrt(np.mean((qa - qb) ** 2)))
