import numpy as np
import pytest
from scipy.interpolate import RegularGridInterpolator

from lookmatch.apply import apply_lut
from lookmatch.export.cube import Cube, identity_table


def _random_cube(size: int = 9, seed: int = 0) -> Cube:
    return Cube(np.random.default_rng(seed).random((size, size, size, 3)))


@pytest.mark.parametrize("size", [2, 17, 33])
def test_identity_leaves_image_unchanged(size: int) -> None:
    img = np.random.default_rng(1).random((40, 30, 3))
    out = apply_lut(img, Cube(identity_table(size)))
    np.testing.assert_allclose(out, img, atol=1e-12)


def test_identity_float32_unchanged() -> None:
    img = np.random.default_rng(2).random((20, 20, 3)).astype(np.float32)
    out = apply_lut(img, Cube(identity_table(33)))
    assert out.dtype == np.float32
    np.testing.assert_allclose(out, img, atol=1e-6)


def test_grid_points_hit_table_exactly() -> None:
    cube = _random_cube(5)
    idx = np.array([[0, 0, 0], [4, 4, 4], [1, 2, 3], [4, 0, 2]])
    out = apply_lut(idx / 4.0, cube)
    np.testing.assert_allclose(out, cube.table[idx[:, 0], idx[:, 1], idx[:, 2]])


def test_cell_center_is_mean_of_corners() -> None:
    cube = _random_cube(3)
    out = apply_lut(np.array([[0.25, 0.25, 0.25]]), cube)
    corners = cube.table[:2, :2, :2].reshape(-1, 3)
    np.testing.assert_allclose(out[0], corners.mean(axis=0), atol=1e-12)


def test_affine_lut_is_reproduced_everywhere() -> None:
    # Trilinear interpolation is exact for any affine color transform.
    a = np.array([[0.9, 0.1, 0.0], [0.05, 0.8, 0.1], [0.0, 0.2, 0.7]])
    b = np.array([0.02, -0.01, 0.05])
    table = identity_table(7) @ a.T + b
    pts = np.random.default_rng(3).random((1000, 3))
    np.testing.assert_allclose(apply_lut(pts, Cube(table)), pts @ a.T + b, atol=1e-12)


def test_matches_scipy_regular_grid_interpolator() -> None:
    cube = _random_cube(9, seed=4)
    grid = np.linspace(0, 1, 9)
    pts = np.random.default_rng(5).random((2000, 3))
    expected = np.stack(
        [
            RegularGridInterpolator((grid, grid, grid), cube.table[..., c])(pts)
            for c in range(3)
        ],
        axis=-1,
    )
    np.testing.assert_allclose(apply_lut(pts, cube), expected, atol=1e-12)


def test_simple_red_lift() -> None:
    table = identity_table(17)
    table[..., 0] += 0.1
    img = np.full((2, 2, 3), 0.4)
    out = apply_lut(img, Cube(table))
    np.testing.assert_allclose(out[..., 0], 0.5, atol=1e-12)
    np.testing.assert_allclose(out[..., 1:], 0.4, atol=1e-12)


def test_values_outside_domain_are_clamped() -> None:
    cube = _random_cube(5, seed=6)
    out = apply_lut(np.array([[-0.5, 0.0, 1.7], [0.0, 0.0, 1.0]]), cube)
    np.testing.assert_allclose(out[0], out[1])


def test_custom_domain() -> None:
    table = identity_table(9) * 2.0  # identity over the domain [0, 2]
    cube = Cube(table, domain_min=(0.0, 0.0, 0.0), domain_max=(2.0, 2.0, 2.0))
    pts = np.random.default_rng(7).random((100, 3)) * 2.0
    np.testing.assert_allclose(apply_lut(pts, cube), pts, atol=1e-12)


def test_chunking_gives_same_result() -> None:
    cube = _random_cube(9, seed=8)
    img = np.random.default_rng(9).random((37, 23, 3))
    whole = apply_lut(img, cube)
    chunked = apply_lut(img, cube, chunk_pixels=100)
    np.testing.assert_array_equal(whole, chunked)


def test_keeps_shape() -> None:
    cube = Cube(identity_table(5))
    assert apply_lut(np.zeros((3,)), cube).shape == (3,)
    assert apply_lut(np.zeros((4, 3)), cube).shape == (4, 3)
    assert apply_lut(np.zeros((2, 5, 6, 3)), cube).shape == (2, 5, 6, 3)


def test_rejects_bad_input() -> None:
    cube = Cube(identity_table(5))
    with pytest.raises(TypeError, match="0 to 1"):
        apply_lut(np.zeros((2, 2, 3), dtype=np.uint8), cube)
    with pytest.raises(ValueError, match="3 color channels"):
        apply_lut(np.zeros((2, 2, 4)), cube)
    bad = np.zeros((2, 3))
    bad[1, 1] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        apply_lut(bad, cube)
