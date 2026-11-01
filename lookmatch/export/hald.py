"""Hald CLUT PNG export.

A Hald CLUT stores a 3D LUT as an ordinary image, for apps that read looks as
pictures (RawTherapee's Film Simulation, darktable, G'MIC, ImageMagick's
-hald-clut). A level L Hald has N = L^2 points per side and is L^3 pixels
square. Reading its pixels left to right, top to bottom, pixel i holds the
output color for the input

    red = i mod N,  green = (i div N) mod N,  blue = i div N^2

each divided by N - 1, so red changes fastest. The identity image is a grid of
small color gradients.

lookmatch writes level 8 (64 points per side, 512 x 512 pixels) as an 8-bit
RGB PNG. The 33-point LUT is sampled at 64 points per side with the same
trilinear interpolation every app uses. Apps then interpolate between those
64 points, which is not quite the same as interpolating between the original
33, and 8-bit rounding adds up to half a level. On the test LUT
(tests/fixtures/test_look_33.cube), 99% of colors come out within half a
level of the .cube, and the worst about 3 levels, where the LUT bends most.

Reference: Eskil Steenberg, "Hald CLUT" (2010), as implemented by
ImageMagick's hald: and -hald-clut.
"""

from pathlib import Path

import numpy as np
import numpy.typing as npt
from PIL import Image

from lookmatch.apply import apply_lut
from lookmatch.export.cube import Cube, identity_table

LEVEL = 8  # 64 points per side, 512 x 512 pixels


def _check_level(level: int) -> None:
    if not 2 <= level <= 16:
        raise ValueError(f"A Hald CLUT level must be between 2 and 16, got {level}.")


def hald_image(cube: Cube, level: int = LEVEL) -> npt.NDArray[np.uint8]:
    """Return a LUT as a Hald CLUT image: (level^3, level^3, 3) 8-bit sRGB."""
    _check_level(level)
    n = level * level
    # identity_table is indexed [r, g, b]; transposing to [b, g, r] and
    # flattening makes red change fastest, as the Hald layout requires.
    inputs = identity_table(n).transpose(2, 1, 0, 3).reshape(-1, 3)
    inputs = cube.domain_min + inputs * np.subtract(cube.domain_max, cube.domain_min)
    outputs = apply_lut(inputs, cube)
    side = level**3
    pixels = np.round(np.clip(outputs, 0.0, 1.0) * 255.0).reshape(side, side, 3)
    return np.asarray(pixels, dtype=np.uint8)


def write_hald(path: str | Path, cube: Cube, level: int = LEVEL) -> None:
    """Write a LUT as a Hald CLUT PNG (8-bit RGB, no color profile)."""
    Image.fromarray(hald_image(cube, level)).save(Path(path), "PNG", optimize=True)


def read_hald(path: str | Path, title: str = "") -> Cube:
    """Read a Hald CLUT image (any level) as a Cube."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Can't find the Hald image '{path}'. Check the path.")
    with Image.open(path) as im:
        pixels = np.asarray(im.convert("RGB"), dtype=np.float64) / 255.0
    side = pixels.shape[0]
    level = round(side ** (1 / 3))
    if pixels.shape[1] != side or level**3 != side:
        raise ValueError(
            f"'{path.name}' isn't a Hald CLUT: it should be square with a side "
            f"of level^3 pixels (512 for level 8), but it is "
            f"{pixels.shape[1]} x {side}."
        )
    n = level * level
    table = pixels.reshape(n, n, n, 3).transpose(2, 1, 0, 3)  # [b, g, r] -> [r, g, b]
    return Cube(table, title=title)
