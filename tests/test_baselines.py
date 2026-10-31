import numpy as np
import ot

from lookmatch import io
from lookmatch.apply import apply_lut
from lookmatch.baselines import (
    identity_lut,
    lalphabeta_stats,
    lalphabeta_to_srgb,
    plain_ot_lut,
    reinhard_lut,
    srgb_to_lalphabeta,
)
from lookmatch.export.cube import Cube, identity_table


def _colors(n: int = 30_000, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    gray = rng.beta(2, 2, (n, 1))
    return np.clip(0.05 + 0.85 * gray + rng.normal(0, 0.08, (n, 3)), 0.02, 0.98)


def _graded(srgb: np.ndarray) -> np.ndarray:
    """A strong warm, contrasty grade."""
    out = srgb.copy()
    out[:, 0] = out[:, 0] ** 0.85
    out[:, 2] = out[:, 2] ** 1.2
    return np.clip(0.5 + 1.15 * (out - 0.5), 0, 1)


def _swd(x: np.ndarray, y: np.ndarray) -> float:
    lab_x, lab_y = io.srgb_to_oklab(x), io.srgb_to_oklab(y)
    return float(
        ot.sliced_wasserstein_distance(lab_x, lab_y, n_projections=200, seed=0)
    )


def test_identity_lut() -> None:
    cube = identity_lut()
    assert isinstance(cube, Cube) and cube.size == 33
    np.testing.assert_array_equal(cube.table, identity_table(33))


def test_lalphabeta_round_trip() -> None:
    srgb = _colors(1000)
    np.testing.assert_allclose(
        lalphabeta_to_srgb(srgb_to_lalphabeta(srgb)), srgb, atol=1e-6
    )


def test_reinhard_matches_mean_and_spread() -> None:
    src, dst = _colors(seed=1), _graded(_colors(seed=2))
    moved = apply_lut(src, reinhard_lut(src, dst))
    mean_m, std_m = lalphabeta_stats(moved)
    mean_t, std_t = lalphabeta_stats(dst)
    # The LUT grid and clipping make it approximate, but close.
    np.testing.assert_allclose(mean_m, mean_t, atol=0.02)
    np.testing.assert_allclose(std_m, std_t, rtol=0.1)


def test_reinhard_same_colors_is_near_identity() -> None:
    src = _colors(seed=3)
    cube = reinhard_lut(src, _colors(seed=4))
    test = _colors(2000, seed=5)
    assert np.abs(apply_lut(test, cube) - test).max() * 255 < 3.0


def test_plain_ot_matches_distribution() -> None:
    src, dst = _colors(seed=6), _graded(_colors(seed=7))
    moved = apply_lut(src, plain_ot_lut(src, dst))
    assert _swd(moved, dst) < 0.25 * _swd(src, dst)


def test_plain_ot_same_colors_is_near_identity() -> None:
    src = _colors(seed=8)
    cube = plain_ot_lut(src, _colors(seed=9))
    test = _colors(2000, seed=10)
    assert np.abs(apply_lut(test, cube) - test).mean() * 255 < 2.0


def test_baselines_are_valid_and_deterministic() -> None:
    src, dst = _colors(seed=11), _graded(_colors(seed=12))
    for make in (reinhard_lut, plain_ot_lut):
        a, b = make(src, dst), make(src, dst)
        assert a.size == 33
        assert a.table.min() >= 0 and a.table.max() <= 1
        np.testing.assert_array_equal(a.table, b.table)
