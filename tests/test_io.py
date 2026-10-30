from pathlib import Path
from typing import Any

import colour
import numpy as np
import pytest
from PIL import Image, ImageCms

from lookmatch import io

DISPLAY_P3 = Path("/System/Library/ColorSync/Profiles/Display P3.icc")


def _random_rgb(n: int = 5000, seed: int = 1) -> np.ndarray:
    return np.random.default_rng(seed).random((n, 3))


# --- sRGB transfer function ------------------------------------------------


def test_srgb_linear_known_values() -> None:
    # IEC 61966-2-1: 0.5 encoded is 0.214041 linear; the two segments meet at
    # 0.04045 encoded / 0.0031308 linear.
    assert io.srgb_to_linear(np.array(0.5)) == pytest.approx(0.2140411, abs=1e-6)
    assert io.srgb_to_linear(np.array(0.04045)) == pytest.approx(0.0031308, abs=1e-6)
    assert io.linear_to_srgb(np.array(0.0031308)) == pytest.approx(0.04045, abs=1e-6)
    assert io.srgb_to_linear(np.array([0.0, 1.0])).tolist() == [0.0, 1.0]


def test_srgb_linear_round_trip() -> None:
    x = np.linspace(-0.2, 1.2, 10_001)
    np.testing.assert_allclose(io.linear_to_srgb(io.srgb_to_linear(x)), x, atol=1e-4)
    np.testing.assert_allclose(io.srgb_to_linear(io.linear_to_srgb(x)), x, atol=1e-4)


# --- OKLab / OKLCh -----------------------------------------------------------


def test_oklab_white_and_black() -> None:
    white = io.linear_srgb_to_oklab(np.array([1.0, 1.0, 1.0]))
    np.testing.assert_allclose(white, [1.0, 0.0, 0.0], atol=1e-4)
    black = io.linear_srgb_to_oklab(np.array([0.0, 0.0, 0.0]))
    np.testing.assert_allclose(black, [0.0, 0.0, 0.0], atol=1e-12)


def test_oklab_round_trip() -> None:
    rgb = _random_rgb()
    back = io.oklab_to_linear_srgb(io.linear_srgb_to_oklab(rgb))
    np.testing.assert_allclose(back, rgb, atol=1e-4)


def test_oklab_matches_colour_science() -> None:
    # Independent implementation: sRGB -> XYZ -> OKLab in colour-science.
    srgb = _random_rgb(500)
    ours = io.srgb_to_oklab(srgb)
    xyz = colour.RGB_to_XYZ(srgb, "sRGB", apply_cctf_decoding=True)
    theirs = colour.XYZ_to_Oklab(xyz)
    np.testing.assert_allclose(ours, theirs, atol=2e-3)


def test_srgb_oklab_round_trip() -> None:
    srgb = _random_rgb()
    np.testing.assert_allclose(
        io.oklab_to_srgb(io.srgb_to_oklab(srgb)), srgb, atol=1e-4
    )


def test_oklch_round_trip_and_range() -> None:
    lab = io.srgb_to_oklab(_random_rgb())
    lch = io.oklab_to_oklch(lab)
    assert np.all(lch[:, 1] >= 0)
    assert np.all((lch[:, 2] >= 0) & (lch[:, 2] < 360))
    np.testing.assert_allclose(io.oklch_to_oklab(lch), lab, atol=1e-6)


def test_conversions_keep_shape_and_float32() -> None:
    img = np.random.default_rng(2).random((7, 5, 3)).astype(np.float32)
    lab = io.srgb_to_oklab(img)
    assert lab.shape == img.shape
    assert lab.dtype == np.float32
    np.testing.assert_allclose(io.oklab_to_srgb(lab), img, atol=1e-4)


def test_conversions_reject_wrong_shape() -> None:
    with pytest.raises(ValueError, match="3 color channels"):
        io.linear_srgb_to_oklab(np.zeros((4, 4)))


# --- Loading -----------------------------------------------------------------


def _save(tmp_path: Path, name: str, img: Image.Image, **kwargs: Any) -> Path:
    path = tmp_path / name
    img.save(path, **kwargs)
    return path


def test_load_png_8bit_exact(tmp_path: Path) -> None:
    arr = np.random.default_rng(3).integers(0, 256, (6, 4, 3), dtype=np.uint8)
    path = _save(tmp_path, "a.png", Image.fromarray(arr))
    img = io.load_image(path)
    assert img.dtype == np.float32
    assert img.shape == (6, 4, 3)
    np.testing.assert_allclose(img, arr / 255.0, atol=1e-7)


def test_load_tiff_and_jpeg(tmp_path: Path) -> None:
    arr = np.full((8, 8, 3), 128, dtype=np.uint8)
    tif = io.load_image(_save(tmp_path, "a.tif", Image.fromarray(arr)))
    np.testing.assert_allclose(tif, 128 / 255.0, atol=1e-7)
    jpg = io.load_image(_save(tmp_path, "a.jpg", Image.fromarray(arr), quality=95))
    assert jpg.shape == (8, 8, 3)
    np.testing.assert_allclose(jpg, 128 / 255.0, atol=3 / 255)


def test_load_grayscale_and_alpha(tmp_path: Path) -> None:
    gray = Image.fromarray(np.full((3, 3), 51, dtype=np.uint8))
    img = io.load_image(_save(tmp_path, "g.png", gray))
    assert img.shape == (3, 3, 3)
    np.testing.assert_allclose(img, 0.2, atol=1e-7)

    rgba = np.zeros((2, 2, 4), dtype=np.uint8)
    rgba[..., 0] = 255
    rgba[..., 3] = 10
    img = io.load_image(_save(tmp_path, "a.png", Image.fromarray(rgba)))
    assert img.shape == (2, 2, 3)
    np.testing.assert_allclose(img[0, 0], [1.0, 0.0, 0.0])


def test_load_16bit_grayscale(tmp_path: Path) -> None:
    arr = np.array([[0, 1000, 65535]], dtype=np.uint16)
    img = io.load_image(_save(tmp_path, "g16.png", Image.fromarray(arr)))
    np.testing.assert_allclose(img[0, :, 0], arr[0] / 65535.0, atol=1e-7)


def test_load_applies_exif_orientation(tmp_path: Path) -> None:
    arr = np.zeros((2, 4, 3), dtype=np.uint8)  # 2 tall, 4 wide
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees clockwise to display
    path = _save(tmp_path, "r.jpg", Image.fromarray(arr), exif=exif)
    assert io.load_image(path).shape == (4, 2, 3)


def test_load_srgb_profile_is_unchanged(tmp_path: Path) -> None:
    arr = np.random.default_rng(4).integers(0, 256, (4, 4, 3), dtype=np.uint8)
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    path = _save(tmp_path, "s.png", Image.fromarray(arr), icc_profile=srgb)
    np.testing.assert_allclose(io.load_image(path), arr / 255.0, atol=1e-7)


@pytest.mark.skipif(not DISPLAY_P3.exists(), reason="needs macOS Display P3 profile")
def test_load_converts_display_p3_to_srgb(tmp_path: Path) -> None:
    # An orange inside both gamuts: the sRGB numbers must differ from the P3
    # numbers and match an independent conversion by colour-science.
    p3 = np.array([[[180, 100, 60]]], dtype=np.uint8)
    path = _save(
        tmp_path, "p3.png", Image.fromarray(p3), icc_profile=DISPLAY_P3.read_bytes()
    )
    img = io.load_image(path)
    expected = colour.RGB_to_RGB(
        p3[0, 0] / 255.0,
        "Display P3",
        "sRGB",
        apply_cctf_decoding=True,
        apply_cctf_encoding=True,
    )
    assert not np.allclose(img[0, 0], p3[0, 0] / 255.0, atol=3 / 255)
    np.testing.assert_allclose(img[0, 0], expected, atol=2 / 255)


def test_load_bad_profile_warns_and_assumes_srgb(tmp_path: Path) -> None:
    arr = np.full((2, 2, 3), 200, dtype=np.uint8)
    path = _save(tmp_path, "b.png", Image.fromarray(arr), icc_profile=b"not a profile")
    with pytest.warns(UserWarning, match="assuming sRGB"):
        img = io.load_image(path)
    np.testing.assert_allclose(img, 200 / 255.0, atol=1e-7)


def test_load_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Can't find"):
        io.load_image(tmp_path / "nope.jpg")


def test_load_unsupported_type(tmp_path: Path) -> None:
    path = tmp_path / "photo.heic"
    path.write_bytes(b"\x00")
    with pytest.raises(ValueError, match="JPEG, PNG, TIFF"):
        io.load_image(path)


class _FakeRaw:
    def __init__(self, data: np.ndarray) -> None:
        self.data = data
        self.kwargs: dict[str, Any] = {}

    def __enter__(self) -> "_FakeRaw":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def postprocess(self, **kwargs: Any) -> np.ndarray:
        self.kwargs = kwargs
        return self.data


def test_load_raw_is_linear_then_srgb(tmp_path: Path, monkeypatch: Any) -> None:
    linear16 = np.array([[[0, 32768, 65535]]], dtype=np.uint16)
    fake = _FakeRaw(linear16)
    monkeypatch.setattr(io.rawpy, "imread", lambda path: fake)
    path = tmp_path / "shot.CR3"
    path.write_bytes(b"\x00")

    img = io.load_image(path)

    assert fake.kwargs["gamma"] == (1, 1)
    assert fake.kwargs["no_auto_bright"] is True
    assert fake.kwargs["output_bps"] == 16
    assert fake.kwargs["use_camera_wb"] is True
    assert fake.kwargs["output_color"] == io.rawpy.ColorSpace.sRGB
    expected = io.linear_to_srgb(linear16 / 65535.0)
    np.testing.assert_allclose(img, expected, atol=1e-6)


# --- Sampling ----------------------------------------------------------------


def test_sample_pixels_is_deterministic() -> None:
    img = np.random.default_rng(5).random((500, 400, 3))
    a = io.sample_pixels(img, max_pixels=1000)
    b = io.sample_pixels(img, max_pixels=1000)
    c = io.sample_pixels(img, max_pixels=1000, seed=1)
    assert a.shape == (1000, 3)
    np.testing.assert_array_equal(a, b)
    assert not np.array_equal(a, c)


def test_sample_pixels_comes_from_image() -> None:
    img = np.random.default_rng(6).random((50, 40, 3))
    sample = io.sample_pixels(img, max_pixels=100)
    flat = img.reshape(-1, 3)
    for px in sample[:10]:
        assert np.any(np.all(flat == px, axis=1))


def test_sample_pixels_small_image_returns_all() -> None:
    img = np.random.default_rng(7).random((10, 10, 3))
    sample = io.sample_pixels(img)
    assert sample.shape == (100, 3)
    np.testing.assert_array_equal(sample, img.reshape(-1, 3))


def test_sample_pixels_default_limit() -> None:
    assert io.MAX_SAMPLES == 100_000
    assert io.DEFAULT_SEED == 0
    img = np.zeros((400, 300, 3), dtype=np.float32)
    sample = io.sample_pixels(img)
    assert sample.shape == (100_000, 3)
    assert sample.dtype == np.float64


def test_load_unreadable_raw_explains(tmp_path: Path) -> None:
    path = tmp_path / "broken.NEF"
    path.write_bytes(b"not really a raw file")
    with pytest.raises(ValueError, match="Can't read the RAW file 'broken.NEF'"):
        io.load_image(path)
