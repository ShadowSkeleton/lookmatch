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


def _photos(count: int, seed: int, cast: float = 0.0) -> list[np.ndarray]:
    """Photos of mostly near-neutral pixels plus one big colored object each.

    The object's color differs from photo to photo; ``cast`` scales it.
    """
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(count):
        lab = _lab(20_000, seed=int(rng.integers(1 << 30)))
        lab[:, 1:] *= 0.15  # most pixels near neutral
        obj = rng.random(lab.shape[0]) < 0.3
        lab[obj, 1:] += cast * rng.normal(0, 0.06, 2)
        out.append(lab)
    return out


def test_neutral_toning_recovers_tint_despite_colored_objects() -> None:
    from lookmatch.toning import fit_neutral_toning

    mine = np.vstack(_photos(10, seed=1, cast=1.0))
    refs = [apply_split_toning(p, TEAL_AND_ORANGE) for p in _photos(8, 2, 1.0)]
    fitted, keep = fit_neutral_toning(mine, refs)
    _close(fitted, TEAL_AND_ORANGE, atol=0.004)
    assert keep[0] > 0.9 and keep[2] > 0.9  # the references agree on the tint


def test_neutral_toning_shrinks_a_tint_the_references_disagree_on() -> None:
    from lookmatch.toning import fit_neutral_toning

    # No look at all; each reference photo has its own color cast.
    rng = np.random.default_rng(5)
    mine = np.vstack(_photos(10, seed=1))
    refs = []
    for p in _photos(6, seed=2):
        p[:, 1:] += rng.normal(0, 0.02, 2)
        refs.append(p)
    raw, unshrunk = fit_neutral_toning(mine, refs, caution=0.0)
    fitted, keep = fit_neutral_toning(mine, refs)
    np.testing.assert_array_equal(unshrunk, 1.0)
    assert np.all(keep < 0.7)
    np.testing.assert_allclose(fitted.as_array(), raw.as_array() * keep[:, None])


def test_neutral_toning_single_reference_and_errors() -> None:
    from lookmatch.toning import fit_neutral_toning

    mine = np.vstack(_photos(3, seed=1))
    ref = apply_split_toning(_photos(1, seed=2)[0], TEAL_AND_ORANGE)
    fitted, keep = fit_neutral_toning(mine, [ref])
    np.testing.assert_array_equal(keep, 1.0)
    _close(fitted, TEAL_AND_ORANGE, atol=0.004)
    with pytest.raises(ValueError, match="at least one reference"):
        fit_neutral_toning(mine, [])


def test_blend_toning() -> None:
    from lookmatch.toning import blend_toning

    zero = SplitToning()
    _close(blend_toning(zero, TEAL_AND_ORANGE, 1.0), TEAL_AND_ORANGE, 1e-12)
    _close(blend_toning(TEAL_AND_ORANGE, zero, 1.0), zero, 1e-12)
    half = blend_toning(zero, TEAL_AND_ORANGE, 0.5)
    np.testing.assert_allclose(half.as_array(), TEAL_AND_ORANGE.as_array() / 2)
