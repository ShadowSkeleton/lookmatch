import numpy as np
import pytest

from lookmatch.metrics import delta_e_2000, delta_e_2000_lab


def test_delta_e_2000_matches_published_test_data() -> None:
    # Sharma, Wu and Dalal (2005), Table 1, pairs 1, 7 and 17.
    lab1 = np.array([[50.0, 2.6772, -79.7751], [50.0, 0.0, 0.0], [50.0, 2.5, 0.0]])
    lab2 = np.array([[50.0, 0.0, -82.7485], [50.0, -1.0, 2.0], [56.0, -27.0, -3.0]])
    expected = [2.0425, 2.3669, 31.9030]
    np.testing.assert_allclose(delta_e_2000_lab(lab1, lab2), expected, atol=1e-4)


def test_identical_colors_have_zero_difference() -> None:
    srgb = np.random.default_rng(0).random((10, 10, 3))
    assert delta_e_2000(srgb, srgb).max() == pytest.approx(0.0, abs=1e-9)


def test_one_level_difference_is_small() -> None:
    gray = np.full((1, 3), 0.5)
    d = delta_e_2000(gray, gray + 1 / 255)
    assert 0.2 < float(d[0]) < 1.0


def test_shape() -> None:
    a = np.zeros((4, 5, 3))
    assert delta_e_2000(a, a).shape == (4, 5)


def test_sliced_wasserstein() -> None:
    from lookmatch.metrics import sliced_wasserstein

    rng = np.random.default_rng(0)
    a = rng.normal(0, 0.05, (20_000, 3))
    b = rng.normal(0, 0.05, (20_000, 3))
    assert sliced_wasserstein(a, a) == 0.0
    assert sliced_wasserstein(a, b) < 0.003  # same distribution
    # A shift by s along a direction d: 1D shift s (d . u) on direction u,
    # whose RMS over random directions is s / sqrt(3).
    shifted = sliced_wasserstein(a, a + [0.06, 0, 0])
    assert shifted == pytest.approx(0.06 / np.sqrt(3), rel=0.15)
    assert sliced_wasserstein(a, b) == sliced_wasserstein(a, b)  # repeatable
    with pytest.raises(ValueError):
        sliced_wasserstein(a, np.zeros((0, 3)))


def test_lightness_distance() -> None:
    from lookmatch.metrics import lightness_distance

    rng = np.random.default_rng(0)
    lab = np.column_stack([rng.random(10_000), np.zeros((10_000, 2))])
    assert lightness_distance(lab, lab) == 0.0
    shifted = lab + [0.05, 0.3, 0.3]  # color changes don't count
    assert lightness_distance(lab, shifted) == pytest.approx(0.05)
    with pytest.raises(ValueError):
        lightness_distance(lab, np.zeros((0, 3)))


def test_ssim_lightness() -> None:
    from lookmatch.metrics import ssim_lightness

    rng = np.random.default_rng(0)
    y, x = np.mgrid[0:64, 0:96] / 96
    photo = np.clip(np.stack([x, y, 0.5 * (x + y)], -1), 0, 1)
    assert ssim_lightness(photo, photo) == pytest.approx(1.0)
    gentle = np.clip(photo * 0.95 + 0.02, 0, 1)  # smooth tone change
    noisy = np.clip(photo + rng.normal(0, 0.08, photo.shape), 0, 1)
    banded = np.round(photo * 4) / 4  # posterized
    assert ssim_lightness(photo, gentle) > 0.95
    assert ssim_lightness(photo, noisy) < 0.5
    assert ssim_lightness(photo, banded) < ssim_lightness(photo, gentle)
    with pytest.raises(ValueError, match="same size"):
        ssim_lightness(photo, photo[:10])
