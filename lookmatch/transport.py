"""Sliced optimal transport in OKLab for residual color.

After the tone curve and split toning, some color differences remain: how a
look treats particular hues, such as pushing skies toward teal or muting
greens. Optimal transport moves each of the user's colors so the whole set of
colors matches the reference's distribution, while moving colors as little
as possible overall.

Method: iterative distribution transfer, implemented from F. Pitié, A.
Kokaram and R. Dahyot, "Automated colour grading using colour distribution
transfer," Computer Vision and Image Understanding 107, 2007. Each iteration:

1. Pick a random rotation of the 3D color space.
2. Project both color sets onto the 3 rotated axes.
3. On each axis, match the 1D distributions exactly: the k-th smallest input
   value moves to the same quantile of the reference values (this is the
   optimal transport map in one dimension).
4. Rotate the moves back and apply them.

Repeating with new rotations makes the full 3D distributions match. Random
rotations come from a generator with a fixed seed, so results are exactly
repeatable.

``strength`` blends between no change (0) and the full transport (1), so the
residual step can be dialed down when the scenes differ.
"""

from typing import Any

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.floating[Any]]

ITERATIONS = 20
DEFAULT_SEED = 0


def _check(colors: npt.ArrayLike, what: str) -> npt.NDArray[np.float64]:
    v = np.asarray(colors, dtype=np.float64)
    if v.ndim != 2 or v.shape[1] != 3:
        raise ValueError(
            f"The {what} colors need shape (N, 3) with 3 color channels, got {v.shape}."
        )
    if v.shape[0] == 0:
        raise ValueError(f"The {what} photos gave no pixels to measure.")
    if not np.all(np.isfinite(v)):
        raise ValueError(f"The {what} colors contain NaN or infinite values.")
    return v


def _random_rotation(rng: np.random.Generator) -> npt.NDArray[np.float64]:
    """Return a uniformly random 3x3 rotation.

    Built from the QR decomposition of a Gaussian matrix, with the sign fix
    of Mezzadri (2007) so every rotation is equally likely.
    """
    q, r = np.linalg.qr(rng.standard_normal((3, 3)))
    return q * np.sign(np.diag(r))


def _match_1d(
    x: npt.NDArray[np.float64], y_sorted: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    """Move each x to the reference value at the same quantile (1D OT)."""
    n, m = x.size, y_sorted.size
    ranks = np.empty(n, dtype=np.float64)
    ranks[np.argsort(x, kind="stable")] = np.arange(n)
    quantile = (ranks + 0.5) / n
    return np.interp(quantile, (np.arange(m) + 0.5) / m, y_sorted)


def sliced_transport(
    source: npt.ArrayLike,
    target: npt.ArrayLike,
    strength: float = 1.0,
    iterations: int = ITERATIONS,
    seed: int = DEFAULT_SEED,
) -> npt.NDArray[np.float64]:
    """Move source colors so their distribution matches the target's.

    ``source`` and ``target`` are (N, 3) and (M, 3) OKLab colors; N and M may
    differ. Returns the moved source colors, in the same order, so each row
    is the destination of the same input color.
    """
    if not 0.0 <= strength <= 1.0:
        raise ValueError(f"The transport strength must be from 0 to 1, got {strength}.")
    x0 = _check(source, "input")
    y = _check(target, "reference")
    if strength == 0.0:
        return x0.copy()

    rng = np.random.default_rng(seed)
    x = x0.copy()
    for _ in range(iterations):
        rot = _random_rotation(rng)
        xp, yp = x @ rot, y @ rot
        moved = np.empty_like(xp)
        for axis in range(3):
            moved[:, axis] = _match_1d(xp[:, axis], np.sort(yp[:, axis]))
        x = x + (moved - xp) @ rot.T

    return x0 + strength * (x - x0)
