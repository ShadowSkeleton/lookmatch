"""3D LUT fitting with a Laplacian smoothness term.

Baking turns the measured look (pairs of "this color in your photos" and
"this color in the look") into the 33-point LUT your apps load.

The LUT table T is found by sparse least squares. With P the prior (the LUT
from the tone curve and split toning alone) and D = T - P the correction:

    minimize  (1/N) sum_i |A_i T - y_i|^2               data: hit the targets
            + (lambda / n^3) |L D|^2                    smooth corrections
            + (mu / n^3) |D|^2                          small corrections

- A_i holds the trilinear weights of sample i's 8 surrounding grid points,
  the same interpolation apply.py and editing apps use, so the LUT is fitted
  exactly as it will be read.
- L is the 3D grid Laplacian (each grid point minus the mean of its
  neighbors). Penalizing it keeps neighboring grid colors from jumping,
  which is what shows up as banding.
- The last term pulls the correction toward zero, so grid points far from
  any sample fall back to the prior (tone curve plus split toning), not to
  "no change".

Normalizing by the sample count N and the grid size n^3 keeps the balance
the same however many pixels are sampled. The system is symmetric positive
definite, so it is solved with conjugate gradient, once per channel.

After solving, outputs are clipped to the sRGB gamut [0, 1], and lightness
along the gray axis (black to white) is checked: it must never go down.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import scipy.sparse as sp
from scipy.sparse.linalg import cg

from lookmatch import io
from lookmatch.export.cube import Cube, identity_table

FloatArray = npt.NDArray[np.floating[Any]]

LUT_SIZE = 33
# lambda: weight of the Laplacian term. Tuned on a known look with 60,000
# samples (see docs/method.md): 1.0 blurred real curvature (5.8 levels worst
# error), 0.01 let noise through (6.3 levels p95 with noisy targets); 0.1
# gave 2.4 levels worst on clean data and 3.4 levels p95 with noise.
SMOOTHNESS = 0.1
PRIOR_PULL = 0.01  # mu: weight of the pull toward the prior
CG_TOLERANCE = 1e-10  # relative residual for the conjugate gradient solver
CG_MAX_ITERATIONS = 20_000


@dataclass(frozen=True)
class BakeResult:
    """A baked LUT and the checks run on it."""

    cube: Cube
    gray_monotonic: bool  # lightness never goes down from black to white
    total_variation: float  # mean change between neighboring grid points
    coverage: float  # share of grid cells that had samples nearby


def _check_pairs(
    source: npt.ArrayLike, target: npt.ArrayLike
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    s = np.asarray(source, dtype=np.float64)
    t = np.asarray(target, dtype=np.float64)
    for v, what in ((s, "source"), (t, "target")):
        if v.ndim != 2 or v.shape[1] != 3:
            raise ValueError(
                f"The {what} colors need shape (N, 3) with 3 color channels, got "
                f"{v.shape}."
            )
        if not np.all(np.isfinite(v)):
            raise ValueError(f"The {what} colors contain NaN or infinite values.")
    if s.shape[0] != t.shape[0]:
        raise ValueError(
            "Source and target need the same number of colors, got "
            f"{s.shape[0]} and {t.shape[0]}."
        )
    return np.clip(s, 0.0, 1.0), t


def trilinear_matrix(colors: npt.NDArray[np.float64], n: int) -> sp.csr_matrix:
    """Return the (N, n^3) matrix of trilinear weights, as in apply.py."""
    t = np.clip(colors, 0.0, 1.0) * (n - 1)
    i0 = np.minimum(t.astype(np.intp), n - 2)
    f = t - i0
    rows, cols, vals = [], [], []
    for dr in (0, 1):
        for dg in (0, 1):
            for db in (0, 1):
                d = np.array([dr, dg, db])
                idx = i0 + d
                w = np.prod(np.where(d == 1, f, 1.0 - f), axis=1)
                rows.append(np.arange(colors.shape[0]))
                cols.append((idx[:, 0] * n + idx[:, 1]) * n + idx[:, 2])
                vals.append(w)
    return sp.csr_matrix(
        (np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
        shape=(colors.shape[0], n**3),
    )


def grid_laplacian(n: int) -> sp.csr_matrix:
    """Return the 3D grid Laplacian (graph Laplacian, free edges), (n^3, n^3)."""
    ones = np.ones(n)
    path = sp.diags(
        [-ones[:-1], np.r_[1.0, 2 * ones[1:-1], 1.0], -ones[:-1]], [-1, 0, 1]
    )
    eye = sp.identity(n)
    lap = (
        sp.kron(sp.kron(path, eye), eye)
        + sp.kron(sp.kron(eye, path), eye)
        + sp.kron(sp.kron(eye, eye), path)
    )
    return sp.csr_matrix(lap)


def gray_axis_lightness(table: npt.ArrayLike) -> npt.NDArray[np.float64]:
    """Return OKLab lightness of the LUT's outputs along the gray axis."""
    t = np.asarray(table, dtype=np.float64)
    i = np.arange(t.shape[0])
    return np.asarray(
        io.srgb_to_oklab(np.clip(t[i, i, i], 0, 1))[:, 0], dtype=np.float64
    )


def total_variation(table: npt.ArrayLike) -> float:
    """Return the mean color change between neighboring grid points.

    Each neighbor pair along red, green or blue counts once; the change is
    the Euclidean length of the output difference. An identity LUT of size
    n scores exactly 1 / (n - 1).
    """
    t = np.asarray(table, dtype=np.float64)
    diffs = [np.linalg.norm(np.diff(t, axis=a), axis=-1).ravel() for a in range(3)]
    return float(np.concatenate(diffs).mean())


def _solve(
    system: sp.csr_matrix, rhs: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    """Solve the symmetric positive definite system with conjugate gradient.

    About 15 times faster than a sparse LU factorization here (0.5 s versus
    7 s for a 33-point LUT), and just as deterministic.
    """
    x, info = cg(system, rhs, rtol=CG_TOLERANCE, maxiter=CG_MAX_ITERATIONS)
    if info != 0:
        raise RuntimeError(
            "The LUT fit did not converge. This is a bug in lookmatch; please "
            "report it with your look.json."
        )
    return np.asarray(x, dtype=np.float64)


def bake_lut(
    source: npt.ArrayLike,
    target: npt.ArrayLike,
    prior: npt.ArrayLike | None = None,
    size: int = LUT_SIZE,
    smoothness: float = SMOOTHNESS,
    prior_pull: float = PRIOR_PULL,
    title: str = "",
) -> BakeResult:
    """Fit a LUT that maps source sRGB colors to target sRGB colors.

    ``prior`` is the (size, size, size, 3) table that grid points with no
    samples fall back to: normally the tone curve plus split toning. Without
    it, the identity LUT is used.
    """
    src, dst = _check_pairs(source, target)
    n = size
    p = identity_table(n) if prior is None else np.asarray(prior, dtype=np.float64)
    if p.shape != (n, n, n, 3):
        raise ValueError(
            f"The prior LUT must have shape ({n}, {n}, {n}, 3), got {p.shape}."
        )
    p_flat = p.reshape(-1, 3)
    cells = n**3

    if src.shape[0] == 0:
        correction = np.zeros_like(p_flat)
        coverage = 0.0
    else:
        a = trilinear_matrix(src, n)
        lap = grid_laplacian(n)
        data = (a.T @ a) / src.shape[0]
        reg = (smoothness * (lap.T @ lap) + prior_pull * sp.identity(cells)) / cells
        system = sp.csr_matrix(data + reg)
        rhs = (a.T @ (dst - a @ p_flat)) / src.shape[0]
        correction = np.column_stack([_solve(system, rhs[:, c]) for c in range(3)])
        coverage = float(np.mean(np.asarray(a.sum(axis=0)).ravel() > 0))

    table = np.clip(p_flat + correction, 0.0, 1.0).reshape(n, n, n, 3)
    return BakeResult(
        cube=Cube(table, title=title),
        gray_monotonic=bool(np.all(np.diff(gray_axis_lightness(table)) >= 0)),
        total_variation=total_variation(table),
        coverage=coverage,
    )
