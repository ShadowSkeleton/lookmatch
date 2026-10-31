import numpy as np
import pytest

from lookmatch import io
from lookmatch.skin import (
    hue_drift,
    limit_skin_hue,
    measure_skin_drift,
    skin_mask,
)

# 8-bit sRGB. Skin values are the ColorChecker skin patches.
SKIN = {"light skin": (194, 150, 130), "dark skin": (115, 82, 68)}
NOT_SKIN = {
    "blue sky": (98, 122, 157),
    "foliage": (87, 108, 67),
    "white": (243, 243, 242),
    "black": (20, 20, 20),
    "pure red": (255, 0, 0),
    "pure green": (0, 255, 0),
    "neutral gray": (128, 128, 128),
}


def _srgb(values: dict[str, tuple[int, int, int]]) -> np.ndarray:
    return np.array(list(values.values()), dtype=np.float64) / 255.0


def _rotate_hue(lab: np.ndarray, degrees: float) -> np.ndarray:
    lch = io.oklab_to_oklch(lab)
    lch[..., 2] = (lch[..., 2] + degrees) % 360
    return io.oklch_to_oklab(lch)


def _skin_pixels(n: int = 2000, seed: int = 0) -> np.ndarray:
    """sRGB pixels scattered around the two ColorChecker skin tones."""
    rng = np.random.default_rng(seed)
    base = _srgb(SKIN)[rng.integers(0, 2, n)]
    return np.clip(base + rng.normal(0, 0.02, (n, 3)), 0, 1)


def test_mask_finds_skin() -> None:
    assert skin_mask(_srgb(SKIN)).all()


@pytest.mark.parametrize("name", list(NOT_SKIN))
def test_mask_rejects_non_skin(name: str) -> None:
    assert not skin_mask(_srgb({name: NOT_SKIN[name]}))[0]


def test_mask_keeps_image_shape() -> None:
    img = np.zeros((4, 5, 3))
    img[1, 2] = _srgb(SKIN)[0]
    mask = skin_mask(img)
    assert mask.shape == (4, 5)
    assert mask.sum() == 1 and mask[1, 2]


def test_hue_drift_wraps_around() -> None:
    before = io.oklch_to_oklab(np.array([[0.6, 0.1, 350.0], [0.6, 0.1, 10.0]]))
    after = io.oklch_to_oklab(np.array([[0.6, 0.1, 10.0], [0.6, 0.1, 350.0]]))
    np.testing.assert_allclose(hue_drift(before, after), [20.0, -20.0], atol=1e-9)


def test_no_change_means_no_drift() -> None:
    px = _skin_pixels()
    drift = measure_skin_drift(px, px)
    assert drift.count > 1000
    assert drift.mean_abs == pytest.approx(0.0, abs=1e-9)
    assert drift.p95_abs == pytest.approx(0.0, abs=1e-9)


def test_measures_known_rotation() -> None:
    px = _skin_pixels()
    after = io.oklab_to_srgb(_rotate_hue(io.srgb_to_oklab(px), 10.0))
    drift = measure_skin_drift(px, after)
    assert drift.mean_abs == pytest.approx(10.0, abs=0.01)
    assert drift.p95_abs == pytest.approx(10.0, abs=0.01)
    assert drift.mean_signed == pytest.approx(10.0, abs=0.01)


def test_only_skin_counts() -> None:
    skin = _skin_pixels(1000)
    sky = np.tile(_srgb({"sky": NOT_SKIN["blue sky"]}), (1000, 1))
    before = np.vstack([skin, sky])
    after = before.copy()
    after[1000:] = io.oklab_to_srgb(_rotate_hue(io.srgb_to_oklab(sky), 40.0))
    drift = measure_skin_drift(before, after)
    assert drift.count == pytest.approx(1000, abs=50)
    assert drift.fraction == pytest.approx(0.5, abs=0.03)
    assert drift.mean_abs == pytest.approx(0.0, abs=1e-9)


def test_no_skin_reports_zero() -> None:
    sky = np.tile(_srgb({"sky": NOT_SKIN["blue sky"]}), (100, 1))
    drift = measure_skin_drift(sky, sky)
    assert drift.count == 0
    assert drift.fraction == 0.0
    assert drift.mean_abs == 0.0 and drift.p95_abs == 0.0


def test_limit_skin_hue_caps_large_drift() -> None:
    before = io.srgb_to_oklab(_skin_pixels())
    after = _rotate_hue(before, 10.0)
    after[:, 0] += 0.02  # also brighter: lightness changes must be kept
    mask = np.ones(before.shape[0], dtype=bool)
    limited = limit_skin_hue(before, after, mask, max_degrees=6.0)
    np.testing.assert_allclose(hue_drift(before, limited), 6.0, atol=1e-6)
    np.testing.assert_allclose(limited[:, 0], after[:, 0])
    np.testing.assert_allclose(
        io.oklab_to_oklch(limited)[:, 1], io.oklab_to_oklch(after)[:, 1], atol=1e-12
    )


def test_limit_skin_hue_leaves_small_drift_and_non_skin() -> None:
    before = io.srgb_to_oklab(_skin_pixels())
    after = _rotate_hue(before, 3.0)
    mask = np.ones(before.shape[0], dtype=bool)
    np.testing.assert_allclose(limit_skin_hue(before, after, mask), after)

    big = _rotate_hue(before, 30.0)
    np.testing.assert_array_equal(limit_skin_hue(before, big, ~mask), big)


def test_limit_skips_nearly_gray_pixels() -> None:
    # Hue is meaningless for nearly gray pixels, so they are left alone.
    before = io.oklch_to_oklab(np.array([[0.6, 0.005, 40.0]]))
    after = io.oklch_to_oklab(np.array([[0.6, 0.005, 120.0]]))
    np.testing.assert_array_equal(
        limit_skin_hue(before, after, np.array([True])), after
    )
