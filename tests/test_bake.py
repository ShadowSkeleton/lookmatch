import sys
import time
from pathlib import Path

import numpy as np
import pytest

from lookmatch import io
from lookmatch.apply import apply_lut
from lookmatch.bake import (
    bake_lut,
    gray_axis_lightness,
    total_variation,
    trilinear_matrix,
)
from lookmatch.export.cube import Cube, identity_table

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
import make_fixtures  # noqa: E402

LOOK = make_fixtures.make_test_look()  # a smooth, known look


def _photo_colors(n: int = 60_000, seed: int = 0) -> np.ndarray:
    """sRGB colors spread through the whole cube, denser near neutral."""
    rng = np.random.default_rng(seed)
    gray = rng.random((n, 1))
    tint = rng.normal(0, 0.15, (n, 3))
    return np.clip(gray + tint, 0, 1)


def _known(x: np.ndarray) -> np.ndarray:
    return apply_lut(x, LOOK)


def test_recovers_a_known_look_where_photos_have_colors() -> None:
    src = _photo_colors()
    result = bake_lut(src, _known(src))
    test = _photo_colors(5000, seed=1)
    # Only judge colors the photos actually contain: at least one sample's
    # worth of weight on the nearest grid point. Rare colors fall back to
    # the prior, which test_unseen_colors_fall_back_to_prior checks.
    mass = np.asarray(trilinear_matrix(src, 33).sum(axis=0)).ravel()
    nearest = np.round(test * 32).astype(int)
    seen = mass[(nearest[:, 0] * 33 + nearest[:, 1]) * 33 + nearest[:, 2]] >= 1.0
    assert seen.mean() > 0.9
    error = np.abs(apply_lut(test[seen], result.cube) - _known(test[seen])) * 255
    assert np.percentile(error, 95) < 1.0, f"p95 {np.percentile(error, 95):.2f} levels"
    assert error.max() < 3.0, f"max {error.max():.2f} levels"


def test_no_data_returns_the_prior_exactly() -> None:
    prior = LOOK.table
    result = bake_lut(np.zeros((0, 3)), np.zeros((0, 3)), prior=prior)
    np.testing.assert_allclose(result.cube.table, prior, atol=1e-12)


def test_unseen_colors_fall_back_to_prior_not_identity() -> None:
    # Data only near neutral; saturated corners never seen.
    rng = np.random.default_rng(2)
    src = np.clip(rng.random((30_000, 1)) + rng.normal(0, 0.03, (30_000, 3)), 0, 1)
    prior = LOOK.table
    result = bake_lut(src, _known(src), prior=prior)
    for corner in ([1, 0, 0], [0, 0, 1], [1, 0, 1], [0, 1, 0]):
        idx = tuple(32 * np.array(corner))
        np.testing.assert_allclose(result.cube.table[idx], prior[idx], atol=0.02)
    # ...and not identity, which differs from the prior at these corners.
    assert np.abs(prior - identity_table(33)).max() > 0.02


def test_gray_ramp_has_no_banding() -> None:
    src = _photo_colors()
    result = bake_lut(src, _known(src))
    ramp = np.repeat(np.linspace(0, 1, 4096)[:, None], 3, axis=1)
    baked, true = apply_lut(ramp, result.cube), _known(ramp)
    lightness = io.srgb_to_oklab(baked)[:, 0]
    assert np.all(np.diff(lightness) >= 0), "lightness goes down somewhere"
    assert result.gray_monotonic
    # Within 1 level of the smooth true look everywhere on the ramp...
    assert np.abs(baked - true).max() * 255 < 1.0
    # ...and no sharper bends than the true look has: a band would show as a
    # spike in the second difference.
    bend = np.abs(np.diff(baked, n=2, axis=0)).max()
    assert bend < 2.0 * np.abs(np.diff(true, n=2, axis=0)).max()


def test_noisy_targets_are_smoothed() -> None:
    src = _photo_colors()
    # Each target is off by about 10 levels of random noise.
    noisy = _known(src) + np.random.default_rng(3).normal(0, 0.04, src.shape)
    result = bake_lut(src, noisy)
    assert total_variation(result.cube.table) < 1.2 * total_variation(LOOK.table)
    test = _photo_colors(5000, seed=4)
    error = np.abs(apply_lut(test, result.cube) - _known(test)) * 255
    assert np.percentile(error, 95) < 4.0


def test_output_is_valid_and_reported() -> None:
    src = _photo_colors(20_000)
    result = bake_lut(src, _known(src), title="Snow portrait")
    assert isinstance(result.cube, Cube)
    assert result.cube.size == 33
    assert result.cube.title == "Snow portrait"
    assert result.cube.table.min() >= 0.0 and result.cube.table.max() <= 1.0
    assert 0.0 < result.coverage <= 1.0
    assert result.total_variation == pytest.approx(total_variation(result.cube.table))


def test_gray_axis_lightness_detects_reversal() -> None:
    table = identity_table(9)
    assert np.all(np.diff(gray_axis_lightness(table)) > 0)
    table[4, 4, 4] = [0.2, 0.2, 0.2]  # middle gray turned dark
    assert np.any(np.diff(gray_axis_lightness(table)) < 0)


def test_total_variation_of_identity() -> None:
    # Each step along one axis changes one channel by 1/(n-1).
    assert total_variation(identity_table(33)) == pytest.approx(1 / 32)


def test_is_deterministic() -> None:
    src = _photo_colors(20_000)
    a = bake_lut(src, _known(src))
    b = bake_lut(src, _known(src))
    np.testing.assert_array_equal(a.cube.table, b.cube.table)


def test_fast_enough() -> None:
    src = _photo_colors(200_000, seed=5)
    start = time.perf_counter()
    bake_lut(src, _known(src))
    assert time.perf_counter() - start < 10.0


def test_rejects_bad_input() -> None:
    src = _photo_colors(100)
    with pytest.raises(ValueError, match="same number"):
        bake_lut(src, src[:50])
    with pytest.raises(ValueError, match="3 color channels"):
        bake_lut(src[:, :2], src[:, :2])
    with pytest.raises(ValueError, match="prior"):
        bake_lut(src, src, prior=np.zeros((9, 9, 9, 3)))
