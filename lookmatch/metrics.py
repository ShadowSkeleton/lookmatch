"""Quality and artifact metrics for a fitted look.

ΔE 2000 (CIEDE2000) is the standard measure of how different two colors look
to people: below about 1 is invisible, 2 to 3 is barely noticeable side by
side. It is computed with colour-science, from sRGB through CIE XYZ to
CIELAB under D65, following Sharma, Wu and Dalal (2005).

The other metrics in the project brief are added in task 4.1. ΔE 2000 is
added early because the benchmark needs it.
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
