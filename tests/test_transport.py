import time

import numpy as np
import ot
import pytest

from lookmatch.transport import sliced_transport


def _swd(x: np.ndarray, y: np.ndarray) -> float:
    """Sliced Wasserstein distance from POT, an independent implementation."""
    return float(ot.sliced_wasserstein_distance(x, y, n_projections=200, seed=0))


def _colors(n: int = 20_000, seed: int = 0) -> np.ndarray:
    """OKLab-like colors: lightness spread, two color clusters (sky, foliage)."""
    rng = np.random.default_rng(seed)
    lightness = rng.beta(2, 2, n)
    cluster = rng.random(n) < 0.5
    a = np.where(cluster, -0.03, -0.06) + rng.normal(0, 0.02, n)
    b = np.where(cluster, -0.08, 0.06) + rng.normal(0, 0.02, n)
    return np.column_stack([lightness, a, b])


def _graded(x: np.ndarray) -> np.ndarray:
    """A nonlinear grade: sky pushed to teal, foliage desaturated and warmed."""
    out = x.copy()
    sky = x[:, 2] < 0
    out[sky, 1] -= 0.03
    out[~sky, 1:] *= 0.6
    out[~sky, 2] += 0.02
    out[:, 0] = x[:, 0] ** 1.1
    return out


def test_distribution_distance_drops() -> None:
    source = _colors(seed=1)
    target = _graded(_colors(seed=2))
    before = _swd(source, target)
    after = _swd(sliced_transport(source, target), target)
    assert after < 0.1 * before, f"before {before:.4f}, after {after:.4f}"


def test_a_pure_shift_moves_every_color_by_the_shift() -> None:
    # Optimal transport between a set and its shifted copy is that shift.
    source = _colors(seed=3)
    shift = np.array([0.02, 0.01, -0.03])
    out = sliced_transport(source, source + shift)
    np.testing.assert_allclose(
        out - source, np.broadcast_to(shift, source.shape), atol=0.003
    )


def test_same_distribution_barely_moves() -> None:
    out = sliced_transport(_colors(seed=4), _colors(seed=5))
    moved = np.linalg.norm(out - _colors(seed=4), axis=1)
    assert np.median(moved) < 0.01


def test_strength_blends_linearly() -> None:
    source = _colors(seed=6)
    target = _graded(_colors(seed=7))
    full = sliced_transport(source, target, strength=1.0)
    half = sliced_transport(source, target, strength=0.5)
    none = sliced_transport(source, target, strength=0.0)
    np.testing.assert_array_equal(none, source)
    np.testing.assert_allclose(half, source + 0.5 * (full - source), atol=1e-12)


def test_is_deterministic() -> None:
    source, target = _colors(seed=8), _graded(_colors(seed=9))
    a = sliced_transport(source, target)
    b = sliced_transport(source, target)
    np.testing.assert_array_equal(a, b)
    c = sliced_transport(source, target, seed=1)
    assert not np.array_equal(a, c)
    assert _swd(c, target) < 0.1 * _swd(source, target)


def test_different_sample_counts() -> None:
    source = _colors(12_000, seed=10)
    target = _graded(_colors(30_000, seed=11))
    out = sliced_transport(source, target)
    assert out.shape == source.shape
    assert _swd(out, target) < 0.1 * _swd(source, target)


def test_fast_enough_for_100k_pixels() -> None:
    source, target = _colors(100_000, seed=12), _graded(_colors(100_000, seed=13))
    start = time.perf_counter()
    sliced_transport(source, target)
    assert time.perf_counter() - start < 5.0


def test_rejects_bad_input() -> None:
    good = _colors(100)
    with pytest.raises(ValueError, match="3 color channels"):
        sliced_transport(good[:, :2], good)
    with pytest.raises(ValueError, match="no pixels"):
        sliced_transport(good[:0], good)
    with pytest.raises(ValueError, match="strength"):
        sliced_transport(good, good, strength=1.5)
    bad = good.copy()
    bad[0, 0] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        sliced_transport(bad, good)
