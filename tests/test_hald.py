from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from lookmatch.apply import apply_lut
from lookmatch.export.cube import Cube, identity_table, read_cube
from lookmatch.export.hald import hald_image, read_hald, write_hald

FIXTURES = Path(__file__).parent / "fixtures"


def test_identity_layout_has_red_fastest() -> None:
    im = hald_image(Cube(identity_table(33)))
    assert im.shape == (512, 512, 3)
    assert im.dtype == np.uint8
    flat = im.reshape(-1, 3)
    np.testing.assert_array_equal(flat[0], [0, 0, 0])
    np.testing.assert_array_equal(flat[63], [255, 0, 0])  # red, the fastest
    np.testing.assert_array_equal(flat[63 * 64], [0, 255, 0])
    np.testing.assert_array_equal(flat[63 * 64 * 64], [0, 0, 255])
    np.testing.assert_array_equal(flat[-1], [255, 255, 255])


@pytest.mark.parametrize("level", [2, 4, 8])
def test_identity_round_trips(tmp_path: Path, level: int) -> None:
    path = tmp_path / "identity.png"
    write_hald(path, Cube(identity_table(5)), level)
    back = read_hald(path)
    assert back.size == level * level
    np.testing.assert_allclose(
        back.table, identity_table(level * level), atol=0.5 / 255
    )


def test_hald_applies_like_the_cube(tmp_path: Path) -> None:
    cube = read_cube(FIXTURES / "test_look_33.cube")
    path = tmp_path / "look_hald.png"
    write_hald(path, cube)
    with Image.open(path) as im:
        assert im.size == (512, 512) and im.mode == "RGB"
    hald = read_hald(path)
    colors = np.random.default_rng(0).random((5000, 3))
    difference = np.abs(apply_lut(colors, hald) - apply_lut(colors, cube)) * 255
    # 8-bit rounding plus resampling 33 points to 64 (see export/hald.py).
    assert np.percentile(difference, 99) < 0.6
    assert difference.max() < 3.5


def test_bad_level_and_bad_image(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="level"):
        hald_image(Cube(identity_table(3)), level=1)
    path = tmp_path / "photo.png"
    Image.new("RGB", (300, 200)).save(path)
    with pytest.raises(ValueError, match="isn't a Hald CLUT"):
        read_hald(path)
    with pytest.raises(FileNotFoundError):
        read_hald(tmp_path / "missing.png")
