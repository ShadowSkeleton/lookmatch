"""The benchmark's built-in known looks.

The benchmark builds these in memory. To look at them in an editing app,
export them as .cube files (into bench/looks/generated/, which git ignores):

    .venv/bin/python bench/make_looks.py

Each look is a small formula, so its exact answer is known everywhere and it
is fully reproducible. They are the project's own work (MIT).

Some looks are built from the same pieces lookmatch fits (a tone curve and
shadow/highlight tints), which may flatter lookmatch. Others deliberately are
not: a hue-selective change and a channel mix. Looks made by hand in an
editing app (task 6.1) are the stronger test; add them to bench/looks/ too.
"""

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from lookmatch import io
from lookmatch.export.cube import Cube, identity_table, write_cube
from lookmatch.toning import zone_weights

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "tests" / "fixtures"))
import make_fixtures  # noqa: E402

Lab = npt.NDArray[np.float64]
SIZE = 33


def _s_curve(lightness: Lab, amount: float) -> Lab:
    """Monotonic S-curve: L - amount sin(2 pi L), monotonic for amount < 0.16."""
    return lightness - amount * np.sin(2 * np.pi * lightness)


def _tint(
    lab: Lab, shadows: tuple[float, float], highlights: tuple[float, float]
) -> Lab:
    w = zone_weights(lab[:, 0])
    out = lab.copy()
    out[:, 1:] += w[:, :1] * np.array(shadows) + w[:, 2:] * np.array(highlights)
    return out


def _saturation(lab: Lab, factor: float) -> Lab:
    out = lab.copy()
    out[:, 1:] *= factor
    return out


def teal_orange(lab: Lab) -> Lab:
    """Teal shadows, orange highlights, a little contrast and saturation."""
    out = lab.copy()
    out[:, 0] = _s_curve(lab[:, 0], 0.03)
    return _saturation(_tint(out, (-0.03, -0.03), (0.02, 0.04)), 1.1)


def faded_film(lab: Lab) -> Lab:
    """Lifted blacks, softer highlights, muted color, warm highlights."""
    out = lab.copy()
    out[:, 0] = 0.07 + 0.86 * lab[:, 0]
    return _tint(_saturation(out, 0.8), (-0.008, 0.006), (0.006, 0.02))


def cool_moody(lab: Lab) -> Lab:
    """Darker, desaturated, blue shadows."""
    out = lab.copy()
    out[:, 0] = np.clip(lab[:, 0], 0, 1) ** 1.15
    return _tint(_saturation(out, 0.75), (-0.01, -0.04), (-0.005, -0.01))


def golden_hour(lab: Lab) -> Lab:
    """Warm overall, brighter, richer color."""
    out = lab.copy()
    out[:, 0] = np.clip(lab[:, 0], 0, 1) ** 0.9
    out = _saturation(out, 1.15)
    out[:, 1] += 0.01
    out[:, 2] += 0.03
    return out


def bleach_bypass(lab: Lab) -> Lab:
    """Strong contrast, little color."""
    out = lab.copy()
    out[:, 0] = _s_curve(lab[:, 0], 0.06)
    return _saturation(out, 0.45)


def green_to_teal(lab: Lab) -> Lab:
    """Hue-selective: greens turn toward teal and lose some saturation."""
    lch = io.oklab_to_oklch(lab)
    # Weight 1 for hues 110 to 160 degrees (greens), fading out over 25 degrees.
    distance = np.abs(((lch[:, 2] - 135.0) + 180.0) % 360.0 - 180.0)
    w = np.clip((50.0 - distance) / 25.0, 0.0, 1.0)
    lch[:, 2] += 40.0 * w
    lch[:, 1] *= 1.0 - 0.15 * w
    return np.asarray(io.oklch_to_oklab(lch), dtype=np.float64)


_MIX = np.array([[0.9, 0.1, 0.0], [0.05, 0.85, 0.1], [0.0, 0.15, 0.85]])


def channel_mix(lab: Lab) -> Lab:
    """Mix the channels in linear light, like some film emulations."""
    linear = io.oklab_to_linear_srgb(lab) @ _MIX.T
    return np.asarray(io.linear_srgb_to_oklab(linear), dtype=np.float64)


LOOKS: dict[str, Callable[[Lab], Lab]] = {
    "teal_orange": teal_orange,
    "faded_film": faded_film,
    "cool_moody": cool_moody,
    "golden_hour": golden_hour,
    "bleach_bypass": bleach_bypass,
    "green_to_teal": green_to_teal,
    "channel_mix": channel_mix,
}


def make_look(name: str) -> Cube:
    """Build one known look as a 33-point LUT."""
    if name == "warm_cool_test":
        return make_fixtures.make_test_look()
    grid: Any = io.srgb_to_oklab(identity_table(SIZE).reshape(-1, 3))
    table = np.clip(io.oklab_to_srgb(LOOKS[name](grid)), 0.0, 1.0)
    return Cube(table.reshape(SIZE, SIZE, SIZE, 3), title=name.replace("_", " "))


ALL_LOOKS = ["warm_cool_test", *LOOKS]


def main() -> None:
    """Export every built-in look to bench/looks/generated/."""
    folder = HERE / "looks" / "generated"
    folder.mkdir(parents=True, exist_ok=True)
    for name in ALL_LOOKS:
        write_cube(folder / f"{name}.cube", make_look(name))
        print(f"Wrote bench/looks/generated/{name}.cube")


if __name__ == "__main__":
    main()
