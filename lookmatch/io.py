"""Image and RAW loading, pixel sampling, and color space conversion.

Conventions used across lookmatch:

- An *image* is a float array of shape (H, W, 3) holding sRGB-encoded values,
  nominally in [0, 1].
- *Pixels* are a float array of shape (N, 3).
- Color conversions accept any array whose last axis has 3 channels and keep
  its shape. float32 input stays float32; anything else becomes float64.
"""

import warnings
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import rawpy
from PIL import Image, ImageCms, ImageOps

FloatArray = npt.NDArray[np.floating[Any]]

MAX_SAMPLES = 100_000
DEFAULT_SEED = 0

IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff"})
RAW_EXTENSIONS = frozenset(
    {
        ".3fr", ".ari", ".arw", ".cr2", ".cr3", ".crw", ".dcr", ".dng", ".erf",
        ".fff", ".iiq", ".k25", ".kdc", ".mef", ".mos", ".mrw", ".nef", ".nrw",
        ".orf", ".pef", ".raf", ".raw", ".rw2", ".rwl", ".sr2", ".srf", ".srw",
        ".x3f",
    }
)  # fmt: skip

_SIXTEEN_BIT_GRAY_MODES = frozenset({"I;16", "I;16B", "I;16L", "I;16N"})

# OKLab, from Björn Ottosson, "A perceptual color space for image processing"
# (2020), https://bottosson.github.io/posts/oklab/. M1 maps linear sRGB to an
# LMS-like cone space; M2 maps the cube-rooted LMS to L, a, b. The inverses are
# computed here, not copied, so a round trip is exact to float precision.
_OKLAB_M1 = np.array(
    [
        [0.4122214708, 0.5363325363, 0.0514459929],
        [0.2119034982, 0.6806995451, 0.1073969566],
        [0.0883024619, 0.2817188376, 0.6299787005],
    ]
)
_OKLAB_M2 = np.array(
    [
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660],
    ]
)
_OKLAB_M1_INV = np.linalg.inv(_OKLAB_M1)
_OKLAB_M2_INV = np.linalg.inv(_OKLAB_M2)


def _as_float(x: npt.ArrayLike) -> FloatArray:
    """Return x as float32 if it already is, otherwise as float64."""
    arr = np.asarray(x)
    if arr.dtype == np.float32:
        return arr
    return arr.astype(np.float64)


def _check_channels(x: FloatArray) -> None:
    if x.ndim == 0 or x.shape[-1] != 3:
        raise ValueError(
            f"Expected colors with 3 color channels (last axis), got shape {x.shape}."
        )


def _apply_matrix(x: FloatArray, m: npt.NDArray[np.float64]) -> FloatArray:
    return (x @ m.T.astype(x.dtype)).astype(x.dtype)


# --- sRGB transfer function --------------------------------------------------


def srgb_to_linear(x: npt.ArrayLike) -> FloatArray:
    """Decode sRGB-encoded values to linear light (IEC 61966-2-1).

    Negative inputs are mirrored, so out-of-range values round-trip.
    """
    v = _as_float(x)
    a = np.abs(v)
    out = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    return (np.sign(v) * out).astype(v.dtype)


def linear_to_srgb(x: npt.ArrayLike) -> FloatArray:
    """Encode linear light to sRGB (IEC 61966-2-1).

    Negative inputs are mirrored, so out-of-range values round-trip.
    """
    v = _as_float(x)
    a = np.abs(v)
    out = np.where(a <= 0.0031308, a * 12.92, 1.055 * a ** (1 / 2.4) - 0.055)
    return (np.sign(v) * out).astype(v.dtype)


# --- OKLab / OKLCh -----------------------------------------------------------


def linear_srgb_to_oklab(rgb: npt.ArrayLike) -> FloatArray:
    """Convert linear sRGB to OKLab (Ottosson 2020)."""
    v = _as_float(rgb)
    _check_channels(v)
    lms = _apply_matrix(v, _OKLAB_M1)
    return _apply_matrix(np.cbrt(lms), _OKLAB_M2)


def oklab_to_linear_srgb(lab: npt.ArrayLike) -> FloatArray:
    """Convert OKLab to linear sRGB (Ottosson 2020). Output is not clipped."""
    v = _as_float(lab)
    _check_channels(v)
    lms_cbrt = _apply_matrix(v, _OKLAB_M2_INV)
    return _apply_matrix(lms_cbrt**3, _OKLAB_M1_INV)


def srgb_to_oklab(srgb: npt.ArrayLike) -> FloatArray:
    """Convert sRGB-encoded values to OKLab."""
    return linear_srgb_to_oklab(srgb_to_linear(srgb))


def oklab_to_srgb(lab: npt.ArrayLike) -> FloatArray:
    """Convert OKLab to sRGB-encoded values. Output is not clipped."""
    return linear_to_srgb(oklab_to_linear_srgb(lab))


def oklab_to_oklch(lab: npt.ArrayLike) -> FloatArray:
    """Convert OKLab to OKLCh: lightness, chroma, hue in degrees [0, 360)."""
    v = _as_float(lab)
    _check_channels(v)
    chroma = np.hypot(v[..., 1], v[..., 2])
    hue = np.degrees(np.arctan2(v[..., 2], v[..., 1])) % 360.0
    return np.stack([v[..., 0], chroma, hue], axis=-1).astype(v.dtype)


def oklch_to_oklab(lch: npt.ArrayLike) -> FloatArray:
    """Convert OKLCh (hue in degrees) to OKLab."""
    v = _as_float(lch)
    _check_channels(v)
    h = np.radians(v[..., 2])
    a = v[..., 1] * np.cos(h)
    b = v[..., 1] * np.sin(h)
    return np.stack([v[..., 0], a, b], axis=-1).astype(v.dtype)


# --- Loading -----------------------------------------------------------------


def load_image(path: str | Path) -> npt.NDArray[np.float32]:
    """Load a photo as an sRGB-encoded float32 image of shape (H, W, 3).

    JPEG, PNG and TIFF files are read with Pillow. An embedded color profile
    that is not sRGB is converted to sRGB; with no profile, sRGB is assumed.
    The EXIF orientation is applied so the photo is upright. Alpha is dropped
    and grayscale is copied to all three channels.

    Note: Pillow reads 16-bit RGB PNG/TIFF at 8-bit precision. That is enough
    for fitting a look, which uses color statistics, not fine detail.

    Camera RAW files are decoded with rawpy (LibRaw) to linear sRGB with the
    camera's white balance, no auto brightening and no tone curve, then
    encoded to sRGB.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Can't find the photo '{path}'. Check the path.")

    ext = path.suffix.lower()
    if ext in RAW_EXTENSIONS:
        return _load_raw(path)
    if ext in IMAGE_EXTENSIONS:
        return _load_with_pillow(path)
    raise ValueError(
        f"Can't open '{path.name}': this file type isn't supported. "
        "Use JPEG, PNG, TIFF, or a camera RAW file. For HEIC photos from a "
        "phone, export them as JPEG first."
    )


def _load_raw(path: Path) -> npt.NDArray[np.float32]:
    try:
        with rawpy.imread(str(path)) as raw:
            rgb16 = raw.postprocess(
                gamma=(1, 1),
                no_auto_bright=True,
                output_bps=16,
                use_camera_wb=True,
                output_color=rawpy.ColorSpace.sRGB,
            )
    except rawpy.LibRawError as err:
        version = ".".join(str(n) for n in rawpy.libraw_version)
        raise ValueError(
            f"Can't read the RAW file '{path.name}'. The file may be damaged, or "
            f"the camera may be newer than this RAW decoder (LibRaw {version}) "
            "supports. Try converting it to DNG or exporting a 16-bit TIFF."
        ) from err
    linear = np.clip(rgb16.astype(np.float32) / 65535.0, 0.0, 1.0)
    return linear_to_srgb(linear).astype(np.float32)


def _load_with_pillow(path: Path) -> npt.NDArray[np.float32]:
    with Image.open(path) as opened:
        im = ImageOps.exif_transpose(opened)
        icc = opened.info.get("icc_profile")

    if im.mode in _SIXTEEN_BIT_GRAY_MODES:
        gray = np.asarray(im, dtype=np.float32) / 65535.0
        return np.repeat(gray[..., None], 3, axis=-1)

    # Drop alpha and palettes but keep the modes an ICC profile can describe.
    if im.mode in ("LA", "La"):
        im = im.convert("L")
    elif im.mode not in ("RGB", "L", "CMYK"):
        im = im.convert("RGB")

    if icc:
        im = _to_srgb(im, icc, path.name)
    im = im.convert("RGB")
    return np.asarray(im, dtype=np.float32) / 255.0


def _to_srgb(im: Image.Image, icc: bytes, name: str) -> Image.Image:
    """Convert an image with an embedded ICC profile to sRGB."""
    try:
        profile = ImageCms.ImageCmsProfile(BytesIO(icc))
        if "srgb" in ImageCms.getProfileDescription(profile).lower():
            return im
        srgb = ImageCms.createProfile("sRGB")
        converted = ImageCms.profileToProfile(im, profile, srgb, outputMode="RGB")
        assert converted is not None
        return converted
    except (ImageCms.PyCMSError, OSError, ValueError):
        warnings.warn(
            f"'{name}' has a color profile lookmatch can't read, so it is "
            "assuming sRGB. Colors may be slightly off. Re-export the photo "
            "as sRGB to be sure.",
            UserWarning,
            stacklevel=3,
        )
        return im


# --- Sampling ----------------------------------------------------------------


def sample_pixels(
    image: npt.ArrayLike, max_pixels: int = MAX_SAMPLES, seed: int = DEFAULT_SEED
) -> FloatArray:
    """Pick up to max_pixels pixels at random, the same ones for the same seed.

    Returns an (N, 3) float64 array, whatever the input dtype: all fitting
    math runs on samples, and float32 statistics drift badly. (Averaging a
    61 MP float32 photo gave 0.14 instead of 0.33.) Images with max_pixels
    pixels or fewer are returned whole, in their original order.
    """
    v = np.asarray(image)
    _check_channels(v)
    flat = v.reshape(-1, 3)
    if flat.shape[0] > max_pixels:
        rng = np.random.default_rng(seed)
        idx = np.sort(rng.choice(flat.shape[0], size=max_pixels, replace=False))
        flat = flat[idx]
    return flat.astype(np.float64)


# --- JPEG quality --------------------------------------------------------------

# The example luminance quantization table of the JPEG standard (ITU-T T.81,
# Annex K, Table K.1), in row order. Encoders such as libjpeg
# scale it by the quality setting.
_JPEG_LUMA_TABLE = np.array(
    [
        [16, 11, 10, 16, 24, 40, 51, 61],
        [12, 12, 14, 19, 26, 58, 60, 55],
        [14, 13, 16, 24, 40, 57, 69, 56],
        [14, 17, 22, 29, 51, 87, 80, 62],
        [18, 22, 37, 56, 68, 109, 103, 77],
        [24, 35, 55, 64, 81, 104, 113, 92],
        [49, 64, 78, 87, 103, 121, 120, 101],
        [72, 92, 95, 98, 112, 100, 103, 99],
    ],
    dtype=np.float64,
)


def jpeg_quality(path: str | Path) -> int | None:
    """Estimate the quality setting (1 to 100) a JPEG was saved with.

    Returns None for files that aren't JPEG or can't be read. libjpeg scales
    the standard table by s = 5000 / q below quality 50 and s = 200 - 2 q
    from 50 up, in percent; the average ratio of the file's luminance table
    to the standard one gives s, and s gives the quality. Encoders with their own tables
    (some cameras, Photoshop) land near the libjpeg quality with the same
    file size, which is what matters for a warning about heavy compression.
    """
    try:
        with Image.open(path) as im:
            if im.format != "JPEG":
                return None
            tables = getattr(im, "quantization", None)
    except OSError:  # includes files Pillow can't identify, such as RAW
        return None
    if not tables or 0 not in tables:
        return None
    luma = np.asarray(tables[0], dtype=np.float64).reshape(8, 8)  # row order
    scale = float(np.mean(luma / _JPEG_LUMA_TABLE) * 100.0)
    quality = 5000.0 / scale if scale > 100.0 else (200.0 - scale) / 2.0
    return int(np.clip(round(quality), 1, 100))
