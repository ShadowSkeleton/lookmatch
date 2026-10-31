"""Simple methods to compare lookmatch against, for the benchmark.

Each baseline returns a 33-point LUT, so every method is scored the same way:
applied to photos it never saw.

- identity_lut: do nothing. Any method worse than this is harmful.
- reinhard_lut: Reinhard color transfer, implemented from E. Reinhard,
  M. Ashikhmin, B. Gooch and P. Shirley, "Color transfer between images,"
  IEEE Computer Graphics and Applications 21(5), 2001. Converts to the
  l-alpha-beta space of Ruderman et al. (1998), then shifts and scales each
  channel so its mean and standard deviation match the reference.
  The paper does not say whether its RGB is linear; lookmatch applies the
  paper's RGB-to-LMS matrix to linear sRGB.
- plain_ot_lut: sliced optimal transport at full strength, with no
  neutralizing, tone curve, split toning or skin step, baked with almost no
  smoothing. The tiny smoothing only keeps the LUT defined in colors with no
  samples.
"""

from typing import Any

import numpy as np
import numpy.typing as npt

from lookmatch import io
from lookmatch.bake import bake_lut
from lookmatch.export.cube import Cube, identity_table
from lookmatch.transport import sliced_transport

FloatArray = npt.NDArray[np.floating[Any]]

LUT_SIZE = 33
PLAIN_OT_SMOOTHNESS = 1e-4  # just enough to define colors with no samples

# Reinhard et al. 2001, equation 4 (RGB to LMS) and equations 2-3
# (log LMS to l-alpha-beta). Inverses are computed, not copied.
_RGB_TO_LMS = np.array(
    [
        [0.3811, 0.5783, 0.0402],
        [0.1967, 0.7244, 0.0782],
        [0.0241, 0.1288, 0.8444],
    ]
)
_LMS_TO_LAB = np.diag([1 / np.sqrt(3), 1 / np.sqrt(6), 1 / np.sqrt(2)]) @ np.array(
    [[1.0, 1.0, 1.0], [1.0, 1.0, -2.0], [1.0, -1.0, 0.0]]
)
_LMS_TO_RGB = np.linalg.inv(_RGB_TO_LMS)
_LAB_TO_LMS = np.linalg.inv(_LMS_TO_LAB)
_TINY = 1e-6  # keeps log10 finite for black pixels


def identity_lut(size: int = LUT_SIZE) -> Cube:
    """Return the LUT that changes nothing."""
    return Cube(identity_table(size), title="no change")


def srgb_to_lalphabeta(srgb: npt.ArrayLike) -> npt.NDArray[np.float64]:
    """Convert sRGB colors to Ruderman's l-alpha-beta space."""
    linear = io.srgb_to_linear(np.asarray(srgb, dtype=np.float64))
    lms = np.maximum(linear @ _RGB_TO_LMS.T, _TINY)
    return np.asarray(np.log10(lms) @ _LMS_TO_LAB.T, dtype=np.float64)


def lalphabeta_to_srgb(lab: npt.ArrayLike) -> npt.NDArray[np.float64]:
    """Convert l-alpha-beta colors back to sRGB (not clipped)."""
    lms = 10.0 ** (np.asarray(lab, dtype=np.float64) @ _LAB_TO_LMS.T)
    return np.asarray(io.linear_to_srgb(lms @ _LMS_TO_RGB.T), dtype=np.float64)


def lalphabeta_stats(
    srgb: npt.ArrayLike,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Return the mean and standard deviation of each l-alpha-beta channel."""
    lab = srgb_to_lalphabeta(np.asarray(srgb, dtype=np.float64).reshape(-1, 3))
    return lab.mean(axis=0), lab.std(axis=0)


def reinhard_lut(
    source: npt.ArrayLike, target: npt.ArrayLike, size: int = LUT_SIZE
) -> Cube:
    """Reinhard color transfer from source samples to target samples, as a LUT."""
    mean_s, std_s = lalphabeta_stats(source)
    mean_t, std_t = lalphabeta_stats(target)
    scale = std_t / np.maximum(std_s, _TINY)
    grid = srgb_to_lalphabeta(identity_table(size).reshape(-1, 3))
    moved = (grid - mean_s) * scale + mean_t
    table = np.clip(lalphabeta_to_srgb(moved), 0.0, 1.0).reshape(size, size, size, 3)
    return Cube(table, title="Reinhard transfer")


def plain_ot_lut(
    source: npt.ArrayLike,
    target: npt.ArrayLike,
    size: int = LUT_SIZE,
    seed: int = io.DEFAULT_SEED,
) -> Cube:
    """Full-strength sliced optimal transport in OKLab, baked with no prior look."""
    src = np.clip(np.asarray(source, dtype=np.float64).reshape(-1, 3), 0.0, 1.0)
    dst = np.clip(np.asarray(target, dtype=np.float64).reshape(-1, 3), 0.0, 1.0)
    moved = sliced_transport(io.srgb_to_oklab(src), io.srgb_to_oklab(dst), seed=seed)
    result = bake_lut(
        src,
        np.clip(io.oklab_to_srgb(moved), 0.0, 1.0),
        size=size,
        smoothness=PLAIN_OT_SMOOTHNESS,
        title="plain optimal transport",
    )
    return result.cube
