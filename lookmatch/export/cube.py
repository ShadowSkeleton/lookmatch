"""Adobe/IRIDAS .cube LUT read/write (Cube LUT spec 1.0).

A 3D LUT here is a float array ``table`` of shape (N, N, N, 3), indexed
``table[r, g, b]``: the output color for the input grid point (r, g, b). Grid
point i on each axis sits at i / (N - 1) of the way from DOMAIN_MIN to
DOMAIN_MAX.

In the file, data lines list output colors with red changing fastest, then
green, then blue, as the spec requires.

Reference: Adobe Systems, "Cube LUT Specification", version 1.0, 2013.
"""

import re
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from lookmatch import __version__

FloatArray = npt.NDArray[np.floating[Any]]
Triple = tuple[float, float, float]

MIN_SIZE = 2
MAX_SIZE = 256  # spec limit for LUT_3D_SIZE
DECIMALS = 6  # 5e-7 precision, far below one 16-bit code value (1.5e-5)
DEFAULT_TITLE = "lookmatch"

_DATA_START = re.compile(r"^[-+.\d]")


@dataclass(frozen=True)
class Cube:
    """A 3D LUT with its .cube metadata."""

    table: FloatArray
    title: str = ""
    domain_min: Triple = field(default=(0.0, 0.0, 0.0))
    domain_max: Triple = field(default=(1.0, 1.0, 1.0))

    def __post_init__(self) -> None:
        """Validate the table and normalize it to float64."""
        table = np.asarray(self.table, dtype=np.float64)
        n = table.shape[0] if table.ndim == 4 else 0
        if table.ndim != 4 or table.shape != (n, n, n, 3):
            raise ValueError(
                f"A 3D LUT table must have shape (N, N, N, 3), got {table.shape}."
            )
        if not MIN_SIZE <= n <= MAX_SIZE:
            raise ValueError(
                f"A 3D LUT must have between {MIN_SIZE} and {MAX_SIZE} points per "
                f"side, got {n}."
            )
        if not np.all(np.isfinite(table)):
            raise ValueError("The LUT contains NaN or infinite values.")
        lo = tuple(float(v) for v in self.domain_min)
        hi = tuple(float(v) for v in self.domain_max)
        if (
            len(lo) != 3
            or len(hi) != 3
            or any(a >= b for a, b in zip(lo, hi, strict=True))
        ):
            raise ValueError(
                "DOMAIN_MIN must be smaller than DOMAIN_MAX on every channel, got "
                f"{lo} and {hi}."
            )
        object.__setattr__(self, "table", table)
        object.__setattr__(self, "domain_min", lo)
        object.__setattr__(self, "domain_max", hi)

    @property
    def size(self) -> int:
        """Number of grid points per side (LUT_3D_SIZE)."""
        return int(self.table.shape[0])


def identity_table(size: int) -> npt.NDArray[np.float64]:
    """Return the (size, size, size, 3) table that leaves every color unchanged."""
    grid = np.linspace(0.0, 1.0, size)
    r, g, b = np.meshgrid(grid, grid, grid, indexing="ij")
    return np.stack([r, g, b], axis=-1)


# --- Writing -------------------------------------------------------------------


def _safe_title(title: str) -> str:
    """Make a title that is safe in any app: one line, ASCII, no double quotes.

    The file name keeps the full (for example Chinese) look name.
    """
    text = title.replace('"', "'")
    text = text.encode("ascii", errors="ignore").decode("ascii")
    text = " ".join(text.split())
    return text or DEFAULT_TITLE


def format_cube(cube: Cube) -> str:
    """Return the .cube file text for a LUT."""
    out = StringIO()
    out.write(f"# Created by lookmatch {__version__}\n")
    out.write("# Input and output: display-referred, sRGB-encoded RGB\n")
    out.write(f'TITLE "{_safe_title(cube.title)}"\n')
    out.write(f"LUT_3D_SIZE {cube.size}\n")
    out.write("DOMAIN_MIN " + " ".join(repr(v) for v in cube.domain_min) + "\n")
    out.write("DOMAIN_MAX " + " ".join(repr(v) for v in cube.domain_max) + "\n")
    out.write("\n")
    # table[r, g, b] -> rows with red fastest: iterate b, then g, then r.
    rows = cube.table.transpose(2, 1, 0, 3).reshape(-1, 3)
    rows = np.round(rows, DECIMALS) + 0.0  # + 0.0 turns -0.0 into 0.0
    np.savetxt(out, rows, fmt=f"%.{DECIMALS}f", delimiter=" ")
    return out.getvalue()


def write_cube(path: str | Path, cube: Cube) -> None:
    """Write a LUT as a .cube file (ASCII, LF line endings)."""
    Path(path).write_text(format_cube(cube), encoding="ascii", newline="\n")


# --- Reading -------------------------------------------------------------------


def _numbers(values: list[str], line_no: int, keyword: str) -> list[float]:
    try:
        return [float(v) for v in values]
    except ValueError:
        raise ValueError(
            f"The {keyword} value on line {line_no} isn't a number: "
            f"{' '.join(values)!r}."
        ) from None


def parse_cube(text: str) -> Cube:
    """Parse .cube file text into a Cube.

    Accepts the variations common in files from other apps: CRLF line endings,
    a UTF-8 byte order mark, comments, tabs, keywords in any order, unknown
    keywords (ignored), and LUT_3D_INPUT_RANGE in place of DOMAIN_MIN/MAX.
    """
    title = ""
    size: int | None = None
    domain_min: Triple = (0.0, 0.0, 0.0)
    domain_max: Triple = (1.0, 1.0, 1.0)
    has_1d = False
    data: list[list[float]] = []

    for line_no, raw_line in enumerate(text.lstrip("﻿").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if _DATA_START.match(line):
            values = line.split()
            if len(values) != 3:
                raise ValueError(
                    f"Line {line_no} has {len(values)} values; each data line "
                    "needs 3 numbers (red, green, blue)."
                )
            try:
                data.append([float(v) for v in values])
            except ValueError:
                raise ValueError(
                    f"The .cube file has a value that isn't a number on line "
                    f"{line_no}: {line!r}."
                ) from None
            continue

        keyword, _, rest = line.partition(" ")
        keyword = keyword.upper()
        if data:
            raise ValueError(
                f"The keyword {keyword} on line {line_no} must come before the "
                "data lines."
            )
        args = rest.split()
        if keyword == "TITLE":
            title = rest.strip().strip('"')
        elif keyword == "LUT_3D_SIZE":
            (n,) = _numbers(args[:1] or ["?"], line_no, keyword)
            size = int(n)
        elif keyword == "LUT_1D_SIZE":
            has_1d = True
        elif keyword in ("DOMAIN_MIN", "DOMAIN_MAX"):
            nums = _numbers(args, line_no, keyword)
            if len(nums) != 3:
                raise ValueError(f"{keyword} on line {line_no} needs 3 numbers.")
            triple: Triple = (nums[0], nums[1], nums[2])
            if keyword == "DOMAIN_MIN":
                domain_min = triple
            else:
                domain_max = triple
        elif keyword == "LUT_3D_INPUT_RANGE":
            lo, hi = _numbers(args, line_no, keyword)[:2]
            domain_min, domain_max = (lo, lo, lo), (hi, hi, hi)
        # Other keywords (for example LUT_1D_INPUT_RANGE) don't affect a 3D LUT.

    if has_1d:
        raise ValueError(
            "This .cube file contains a 1D LUT, which lookmatch doesn't support. "
            "Use a 3D LUT."
        )
    if size is None:
        raise ValueError(
            "This .cube file has no LUT_3D_SIZE line, so it isn't a 3D LUT."
        )
    if not MIN_SIZE <= size <= MAX_SIZE:
        raise ValueError(
            f"LUT_3D_SIZE must be between {MIN_SIZE} and {MAX_SIZE}, got {size}."
        )
    if len(data) != size**3:
        raise ValueError(
            f"The .cube file has {len(data)} data lines, but LUT_3D_SIZE {size} "
            f"expected {size**3}. The file may be cut off or damaged."
        )

    # Rows have red fastest, so reshaping gives [b, g, r]; reorder to [r, g, b].
    table = np.array(data, dtype=np.float64).reshape(size, size, size, 3)
    return Cube(
        table.transpose(2, 1, 0, 3),
        title=title,
        domain_min=domain_min,
        domain_max=domain_max,
    )


def read_cube(path: str | Path) -> Cube:
    """Read a .cube file."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Can't find the LUT file '{path}'. Check the path.")
    return parse_cube(path.read_bytes().decode("utf-8-sig", errors="replace"))
