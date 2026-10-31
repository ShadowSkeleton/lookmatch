import numpy as np
import pytest

from lookmatch import io
from lookmatch.neutralize import (
    LUMA,
    Correction,
    apply_correction,
    estimate,
    group_corrections,
)


def _scene(n: int = 20_000, seed: int = 0, white: bool = True) -> np.ndarray:
    """Linear reflectances whose average is neutral gray, plus a white object."""
    rng = np.random.default_rng(seed)
    refl = rng.uniform(0.05, 0.6, (n, 3))
    if white:
        refl[: n // 50] = 0.85  # 2% of the scene is a white object
    return refl


def _light(scene: np.ndarray, illuminant: tuple[float, float, float], k: float = 1.0):
    """Light a linear scene and encode it as sRGB samples."""
    return io.linear_to_srgb(np.clip(scene * np.array(illuminant) * k, 0, 1))


def _cast(est_rgb: np.ndarray) -> np.ndarray:
    return est_rgb / est_rgb[1]


WARM = (1.25, 1.0, 0.7)  # tungsten-like: strong red, weak blue
COOL = (0.85, 1.0, 1.3)  # shade-like


@pytest.mark.parametrize("illuminant", [WARM, COOL, (1.0, 1.0, 1.0)])
def test_recovers_known_cast(illuminant: tuple[float, float, float]) -> None:
    e = estimate(_light(_scene(), illuminant, 0.8))
    assert e.reliable
    expected = np.array(illuminant) / illuminant[1]
    np.testing.assert_allclose(_cast(e.illuminant), expected, rtol=0.03)


def test_illuminant_has_unit_luminance() -> None:
    e = estimate(_light(_scene(), WARM, 0.8))
    assert float(e.illuminant @ LUMA) == pytest.approx(1.0, abs=1e-9)


def test_white_patch_rescues_colorful_scene() -> None:
    # A red-dominated scene fools gray world; a white object does not.
    scene = _scene(white=True)
    scene[:, 0] *= 1.5
    scene[: scene.shape[0] // 50] = 0.85
    srgb = _light(scene, (1.0, 1.0, 1.0), 0.8)
    gray_world = estimate(srgb, blend=1.0)
    white_patch = estimate(srgb, blend=0.0)
    assert _cast(gray_world.illuminant)[0] > 1.3
    np.testing.assert_allclose(_cast(white_patch.illuminant), [1, 1, 1], rtol=0.03)


def test_clipped_pixels_are_ignored() -> None:
    scene = _scene()
    srgb = _light(scene, WARM, 0.8)
    blown = np.tile([1.0, 1.0, 0.95], (5000, 1))  # clipped highlights
    a = estimate(srgb)
    b = estimate(np.vstack([srgb, blown]))
    np.testing.assert_allclose(_cast(a.illuminant), _cast(b.illuminant), rtol=0.01)


def test_exposure_is_median_luminance() -> None:
    scene = _scene()
    bright = estimate(_light(scene, (1, 1, 1), 0.8))
    dark = estimate(_light(scene, (1, 1, 1), 0.4))  # one stop under
    assert bright.median_luminance / dark.median_luminance == pytest.approx(
        2.0, rel=0.01
    )


def test_black_image_is_unreliable() -> None:
    e = estimate(np.zeros((1000, 3)))
    assert not e.reliable
    np.testing.assert_array_equal(e.illuminant, [1.0, 1.0, 1.0])


def test_extreme_cast_is_clamped_and_flagged() -> None:
    e = estimate(_light(_scene(), (1.0, 1.0, 0.02), 0.8))
    assert not e.reliable
    ratio = e.illuminant / e.illuminant.max()
    assert ratio.min() >= 0.25 - 1e-9


# --- Group corrections ---------------------------------------------------------


def test_single_photo_is_left_alone() -> None:
    (c,) = group_corrections([estimate(_light(_scene(), WARM, 0.5))])
    np.testing.assert_allclose(c.white_balance, [1, 1, 1], atol=1e-12)
    assert c.exposure == pytest.approx(1.0)


def test_group_moves_photos_to_shared_average() -> None:
    scene = _scene()
    photos = [_light(scene, WARM, 0.8), _light(scene, COOL, 0.4)]
    estimates = [estimate(p) for p in photos]
    corrections = group_corrections(estimates, exposure_strength=1.0)

    after = [
        estimate(apply_correction(p, c))
        for p, c in zip(photos, corrections, strict=True)
    ]
    # Both photos now share one white balance and one exposure.
    np.testing.assert_allclose(after[0].illuminant, after[1].illuminant, rtol=0.03)
    assert after[0].median_luminance == pytest.approx(
        after[1].median_luminance, rel=0.03
    )
    # The shared white balance is between the two: the group's average is kept.
    shared = _cast(after[0].illuminant)
    assert _cast(np.array(COOL))[0] < shared[0] < _cast(np.array(WARM))[0]


def test_default_exposure_is_half_strength_and_capped() -> None:
    scene = _scene()
    # Two stops apart: each is one stop from the shared exposure.
    two_stops = [
        estimate(_light(scene, (1, 1, 1), 0.8)),
        estimate(_light(scene, (1, 1, 1), 0.2)),
    ]
    c = group_corrections(two_stops)
    assert np.log2(c[0].exposure) == pytest.approx(-0.5, abs=0.02)
    assert np.log2(c[1].exposure) == pytest.approx(0.5, abs=0.02)
    # Eight stops apart: the correction stops at one stop.
    far = [
        estimate(_light(scene, (1, 1, 1), 0.9)),
        estimate(_light(scene, (1, 1, 1), 0.9 / 256)),
    ]
    c = group_corrections(far)
    assert np.log2(c[0].exposure) == pytest.approx(-1.0)
    assert np.log2(c[1].exposure) == pytest.approx(1.0)


def test_unreliable_photo_is_not_corrected_and_not_counted() -> None:
    scene = _scene()
    good = [estimate(_light(scene, WARM, 0.8)), estimate(_light(scene, WARM, 0.8))]
    bad = estimate(np.zeros((500, 3)))
    corrections = group_corrections([*good, bad])
    np.testing.assert_allclose(corrections[2].white_balance, [1, 1, 1])
    assert corrections[2].exposure == 1.0
    np.testing.assert_allclose(corrections[0].white_balance, [1, 1, 1], atol=1e-9)


def test_white_balance_keeps_luminance_of_gray() -> None:
    scene = _scene()
    estimates = [estimate(_light(scene, WARM, 0.8)), estimate(_light(scene, COOL, 0.8))]
    for c in group_corrections(estimates):
        gray = np.array([[0.5, 0.5, 0.5]])
        out = io.srgb_to_linear(
            apply_correction(io.linear_to_srgb(gray), Correction(c.white_balance, 1.0))
        )
        assert float(out[0] @ LUMA) == pytest.approx(float(gray[0] @ LUMA), rel=0.05)


def test_apply_correction_keeps_shape_and_is_unclipped() -> None:
    img = np.full((4, 5, 3), 0.9, dtype=np.float32)
    out = apply_correction(img, Correction(np.array([1.0, 1.0, 1.0]), 2.0))
    assert out.shape == img.shape
    assert out.max() > 1.0


def test_estimate_is_deterministic() -> None:
    srgb = _light(_scene(), WARM, 0.8)
    a, b = estimate(srgb), estimate(srgb)
    np.testing.assert_array_equal(a.illuminant, b.illuminant)
    assert a.median_luminance == b.median_luminance
