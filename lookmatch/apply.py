"""Apply a 3D LUT to images with trilinear interpolation.

Each input color is placed in the LUT grid; the output blends the 8 grid
points of the cell around it, weighted by distance along red, green and blue.
This is the standard trilinear method (the default in DaVinci Resolve), and
it reproduces any affine color transform exactly.

Inputs outside the LUT domain are clamped to its edge, as editing apps do.
"""

from typing import Any

import numpy as np
import numpy.typing as npt

from lookmatch.export.cube import Cube

FloatArray = npt.NDArray[np.floating[Any]]

# About 1M pixels per chunk keeps temporary arrays near 100 MB even for very
# large photos, while staying fast.
CHUNK_PIXELS = 1 << 20


def apply_lut(
    image: npt.ArrayLike, cube: Cube, chunk_pixels: int = CHUNK_PIXELS
) -> FloatArray:
    """Apply a LUT to an image or to pixels, keeping their shape.

    ``image`` holds float values (normally sRGB-encoded, in 0 to 1) with 3
    color channels on the last axis. float32 input gives float32 output;
    other float input gives float64. Interpolation always runs in float64.
    """
    v = np.asarray(image)
    if not np.issubdtype(v.dtype, np.floating):
        raise TypeError(
            "apply_lut expects float color values from 0 to 1, not "
            f"{v.dtype} values. Load photos with lookmatch.io.load_image."
        )
    if v.ndim == 0 or v.shape[-1] != 3:
        raise ValueError(
            f"Expected colors with 3 color channels (last axis), got shape {v.shape}."
        )

    n = cube.size
    table = cube.table.reshape(-1, 3)  # flat index: (r * n + g) * n + b
    lo = np.array(cube.domain_min)
    scale = (n - 1) / (np.array(cube.domain_max) - lo)
    steps = np.array([n * n, n, 1])  # flat-index step for +1 in r, g, b

    flat = v.reshape(-1, 3)
    out = np.empty(
        flat.shape, dtype=np.float32 if v.dtype == np.float32 else np.float64
    )

    for start in range(0, flat.shape[0], chunk_pixels):
        x = flat[start : start + chunk_pixels].astype(np.float64)
        if not np.all(np.isfinite(x)):
            raise ValueError("The image contains NaN or infinite values.")

        t = np.clip((x - lo) * scale, 0.0, n - 1)
        i0 = np.minimum(t.astype(np.intp), n - 2)  # floor, since t >= 0
        f = t - i0
        base = i0 @ steps
        fr, fg, fb = f[:, 0:1], f[:, 1:2], f[:, 2:3]
        dr, dg, db = steps

        # Interpolate along blue, then green, then red.
        c00 = _lerp(table[base], table[base + db], fb)
        c01 = _lerp(table[base + dg], table[base + dg + db], fb)
        c10 = _lerp(table[base + dr], table[base + dr + db], fb)
        c11 = _lerp(table[base + dr + dg], table[base + dr + dg + db], fb)
        c0 = _lerp(c00, c01, fg)
        c1 = _lerp(c10, c11, fg)
        out[start : start + chunk_pixels] = _lerp(c0, c1, fr)

    return out.reshape(v.shape)


def _lerp(
    a: npt.NDArray[np.float64], b: npt.NDArray[np.float64], t: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    return a + (b - a) * t
