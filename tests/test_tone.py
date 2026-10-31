from collections.abc import Callable

import numpy as np
import pytest

from lookmatch.look import Look
from lookmatch.tone import GRID, apply_tone_curve, fit_tone_curve

Curve = Callable[[np.ndarray], np.ndarray]

KNOWN_CURVES: dict[str, Curve] = {
    "s-curve": lambda x: x - 0.06 * np.sin(2 * np.pi * x),
    "brighter (gamma 0.8)": lambda x: x**0.8,
    "darker (gamma 1.25)": lambda x: x**1.25,
    "faded film": lambda x: 0.08 + 0.84 * x,
    "crushed blacks": lambda x: np.clip((x - 0.05) / 0.95, 0, 1),
}


def _lightness(n: int = 100_000, seed: int = 0) -> np.ndarray:
    """A photo-like spread of lightness: mostly midtones, some deep shadows."""
    rng = np.random.default_rng(seed)
    return np.clip(rng.beta(2.0, 2.2, n), 0, 1)


@pytest.mark.parametrize("name", list(KNOWN_CURVES))
def test_recovers_known_curve(name: str) -> None:
    f = KNOWN_CURVES[name]
    inputs = _lightness(seed=1)
    reference = f(_lightness(seed=2))  # same kind of scene, different pixels
    curve = fit_tone_curve(inputs, reference)

    # Compare where the photos have data (1st to 99th percentile of input).
    lo, hi = np.percentile(inputs, [1, 99])
    covered = (GRID >= lo) & (GRID <= hi)
    error = np.abs(curve[covered] - f(GRID[covered]))
    assert error.max() < 0.01, f"{name}: max error {error.max():.4f}"


def test_same_photos_give_identity() -> None:
    curve = fit_tone_curve(_lightness(seed=3), _lightness(seed=4))
    covered = (GRID > 0.05) & (GRID < 0.95)
    np.testing.assert_allclose(curve[covered], GRID[covered], atol=0.01)


def test_curve_shape_and_range() -> None:
    curve = fit_tone_curve(_lightness(seed=5), _lightness(seed=6) ** 0.7)
    assert curve.shape == (256,)
    assert curve.dtype == np.float64
    assert curve.min() >= 0.0 and curve.max() <= 1.0
    assert np.all(np.diff(curve) >= 0)


def test_always_monotonic_even_for_odd_data() -> None:
    rng = np.random.default_rng(7)
    for seed in range(5):
        a = rng.random(5000) ** rng.uniform(0.3, 3)
        b = np.concatenate([rng.random(2500) * 0.3, 0.7 + rng.random(2500) * 0.3])
        curve = fit_tone_curve(a, b)
        assert np.all(np.diff(curve) >= 0), seed


def test_clipped_highlights_are_handled() -> None:
    inputs = _lightness(seed=8)
    inputs[:20_000] = 1.0  # a fifth of the photo is blown out
    curve = fit_tone_curve(inputs, _lightness(seed=9))
    assert np.all(np.diff(curve) >= 0)
    assert np.all(np.isfinite(curve))


def test_extends_gently_beyond_the_data() -> None:
    # Input only covers the midtones; outside it, the curve continues at
    # slope 1 from the fitted ends, never steeper, and stays in [0, 1].
    inputs = 0.3 + 0.4 * _lightness(seed=10)
    reference = 0.25 + 0.4 * _lightness(seed=11)
    curve = fit_tone_curve(inputs, reference)
    below = GRID < inputs.min()
    above = GRID > inputs.max()
    assert np.all(np.diff(curve[below]) <= np.diff(GRID[below]) + 1e-9)
    assert np.all(np.diff(curve[above]) <= np.diff(GRID[above]) + 1e-9)
    assert curve[0] >= 0 and curve[-1] <= 1


def test_apply_tone_curve() -> None:
    curve = GRID**0.8
    x = np.array([0.0, 0.25, 0.5, 1.0])
    np.testing.assert_allclose(apply_tone_curve(x, curve), x**0.8, atol=2e-4)
    assert apply_tone_curve(np.zeros((4, 5)), curve).shape == (4, 5)


def test_is_deterministic() -> None:
    a = fit_tone_curve(_lightness(seed=12), _lightness(seed=13) ** 1.2)
    b = fit_tone_curve(_lightness(seed=12), _lightness(seed=13) ** 1.2)
    np.testing.assert_array_equal(a, b)


def test_fits_in_look_json() -> None:
    curve = fit_tone_curve(_lightness(seed=14), _lightness(seed=15) ** 0.9)
    Look(name="t", tone_curve=curve.tolist()).validate()


def test_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="no pixels"):
        fit_tone_curve(np.array([]), _lightness())
    bad = _lightness()
    bad[3] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        fit_tone_curve(bad, _lightness())


def test_end_points_recover_black_and_white_points() -> None:
    from lookmatch.tone import fit_end_points

    faded = KNOWN_CURVES["faded film"]  # a straight line: end points say it all
    inputs = _lightness(seed=1)
    curve = fit_end_points(inputs, faded(_lightness(seed=2)))
    lo, hi = np.percentile(inputs, [1, 99])
    covered = (GRID >= lo) & (GRID <= hi)
    assert np.abs(curve[covered] - faded(GRID[covered])).max() < 0.01


def test_end_points_ignore_how_bright_the_scenes_are() -> None:
    from lookmatch.tone import fit_end_points

    # Same black and white, but the reference scenes are mostly bright.
    rng = np.random.default_rng(0)
    inputs = np.concatenate([[0.0, 1.0] * 1000, rng.beta(2, 2, 100_000)])
    bright = np.concatenate([[0.0, 1.0] * 1000, rng.beta(5, 2, 100_000)])
    curve = fit_end_points(inputs, bright)
    assert np.abs(curve - GRID).max() < 0.01  # unchanged
    assert np.abs(fit_tone_curve(inputs, bright) - GRID).max() > 0.1  # full fit


def test_end_points_and_blend_never_decrease() -> None:
    from lookmatch.tone import blend_curves, fit_end_points

    rng = np.random.default_rng(3)
    safe = fit_end_points(rng.random(1000), rng.random(1000) ** 3)
    full = fit_tone_curve(rng.random(1000), rng.random(1000) ** 3)
    for w in (0.0, 0.3, 1.0):
        assert np.all(np.diff(blend_curves(safe, full, w)) >= 0)
    np.testing.assert_allclose(blend_curves(safe, full, 0.0), safe)
    np.testing.assert_allclose(blend_curves(safe, full, 1.0), full)
    np.testing.assert_allclose(fit_end_points(np.full(10, 0.5), rng.random(10)), GRID)
