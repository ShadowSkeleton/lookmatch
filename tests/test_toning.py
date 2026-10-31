import numpy as np
import pytest

from lookmatch.toning import (
    SplitToning,
    apply_split_toning,
    fit_split_toning,
    zone_weights,
)

TEAL_AND_ORANGE = SplitToning(
    shadows=(-0.02, -0.03),  # OKLab a, b: teal
    midtones=(0.0, 0.0),
    highlights=(0.012, 0.03),  # warm
)


def _lab(
    n: int = 100_000, seed: int = 0, lo: float = 0.0, hi: float = 1.0
) -> np.ndarray:
    """Photo-like OKLab samples: spread of lightness, mostly muted colors."""
    rng = np.random.default_rng(seed)
    lightness = lo + (hi - lo) * rng.beta(2.0, 2.0, n)
    ab = rng.normal(0.0, 0.04, (n, 2))
    return np.column_stack([lightness, ab])


def _close(a: SplitToning, b: SplitToning, atol: float) -> None:
    for zone in ("shadows", "midtones", "highlights"):
        np.testing.assert_allclose(
            getattr(a, zone), getattr(b, zone), atol=atol, err_msg=zone
        )


def test_zone_weights_add_up_to_one() -> None:
    lightness = np.linspace(0, 1, 101)
    w = zone_weights(lightness)
    assert w.shape == (101, 3)
    np.testing.assert_allclose(w.sum(axis=1), 1.0)
    np.testing.assert_allclose(w[0], [1, 0, 0])
    np.testing.assert_allclose(w[50], [0.25, 0.5, 0.25])
    np.testing.assert_allclose(w[-1], [0, 0, 1])


def test_recovers_known_tint() -> None:
    inputs = _lab(seed=1)
    reference = apply_split_toning(_lab(seed=2), TEAL_AND_ORANGE)
    fitted = fit_split_toning(inputs, reference)
    _close(fitted, TEAL_AND_ORANGE, atol=0.002)


def test_recovers_midtone_tint() -> None:
    known = SplitToning(
        shadows=(0.0, 0.0), midtones=(0.015, -0.02), highlights=(0.0, 0.0)
    )
    fitted = fit_split_toning(_lab(seed=3), apply_split_toning(_lab(seed=4), known))
    _close(fitted, known, atol=0.002)


def test_no_tint_gives_zero() -> None:
    fitted = fit_split_toning(_lab(seed=5), _lab(seed=6))
    _close(fitted, SplitToning(), atol=0.002)


def test_apply_then_fit_is_consistent() -> None:
    inputs = _lab(seed=7)
    fitted = fit_split_toning(inputs, apply_split_toning(inputs, TEAL_AND_ORANGE))
    _close(fitted, TEAL_AND_ORANGE, atol=1e-3)


def test_missing_zone_stays_calm() -> None:
    # No bright pixels at all: the highlight offset can't be measured, so it
    # must stay small instead of being extrapolated wildly.
    inputs = _lab(seed=8, hi=0.55)
    reference = apply_split_toning(_lab(seed=9, hi=0.55), TEAL_AND_ORANGE)
    fitted = fit_split_toning(inputs, reference)
    assert np.all(np.isfinite(fitted.highlights))
    assert np.abs(fitted.highlights).max() < 0.06
    np.testing.assert_allclose(fitted.shadows, TEAL_AND_ORANGE.shadows, atol=0.004)


def test_apply_keeps_lightness_and_shape() -> None:
    img = _lab(1000, seed=10).reshape(10, 100, 3)
    out = apply_split_toning(img, TEAL_AND_ORANGE)
    assert out.shape == img.shape
    np.testing.assert_array_equal(out[..., 0], img[..., 0])
    black = apply_split_toning(np.array([[0.0, 0.0, 0.0]]), TEAL_AND_ORANGE)
    np.testing.assert_allclose(black[0, 1:], TEAL_AND_ORANGE.shadows)


def test_hue_and_chroma() -> None:
    hue, chroma = SplitToning(highlights=(0.0, 0.03)).hue_chroma("highlights")
    assert hue == pytest.approx(90.0)
    assert chroma == pytest.approx(0.03)


def test_is_deterministic() -> None:
    a = fit_split_toning(_lab(seed=11), _lab(seed=12))
    b = fit_split_toning(_lab(seed=11), _lab(seed=12))
    assert a == b


def test_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="no pixels"):
        fit_split_toning(np.zeros((0, 3)), _lab())
    with pytest.raises(ValueError, match="3 color channels"):
        fit_split_toning(np.zeros((10, 2)), _lab())
