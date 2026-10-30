"""Generate the hand-made test LUT and the test chart (task 1.4).

Run from the repo root to rewrite the committed files:

    .venv/bin/python tests/fixtures/make_fixtures.py

Both outputs are fully determined by this script, and a test checks that the
committed files still match it.
"""

import json
from pathlib import Path
from typing import Any

import colour
import numpy as np
import numpy.typing as npt
from PIL import Image, ImageCms

from lookmatch import io
from lookmatch.export.cube import Cube, identity_table, write_cube

HERE = Path(__file__).parent

# --- Test look: warm shadows, cool highlights, gentle S-curve -----------------

LUT_SIZE = 33
WARM_SHADOWS = (0.012, 0.035)  # OKLab (a, b) offset at full shadow weight
COOL_HIGHLIGHTS = (-0.012, -0.035)  # OKLab (a, b) offset at full highlight weight
S_CURVE = 0.03  # peak lightness change of the S-curve


def _smoothstep(edge0: float, edge1: float, x: npt.NDArray[Any]) -> npt.NDArray[Any]:
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def make_test_look() -> Cube:
    """Build the test look as a 33-point LUT.

    Defined in OKLab so it is easy to describe: lightness gets a gentle
    S-curve, L - 0.03 sin(2 pi L), which is monotonic because its slope is at
    least 1 - 0.06 pi > 0. Shadows shift warm and highlights shift cool, with
    weights (1 - L)^2 and L^2 tapered to zero at pure black and pure white so
    those stay neutral. The result is clipped to the sRGB gamut.
    """
    lab = io.srgb_to_oklab(identity_table(LUT_SIZE))
    lightness = np.clip(lab[..., 0], 0.0, 1.0)

    shadow_w = (1 - lightness) ** 2 * _smoothstep(0.0, 0.15, lightness)
    highlight_w = lightness**2 * _smoothstep(0.0, 0.15, 1 - lightness)

    out = lab.copy()
    out[..., 0] = lab[..., 0] - S_CURVE * np.sin(2 * np.pi * lightness)
    for i in (0, 1):
        out[..., i + 1] += shadow_w * WARM_SHADOWS[i] + highlight_w * COOL_HIGHLIGHTS[i]

    table = np.clip(io.oklab_to_srgb(out), 0.0, 1.0)
    return Cube(table, title="lookmatch test look (warm shadows, cool highlights)")


# --- Test chart ------------------------------------------------------------------

CHART_W, CHART_H = 1280, 1020
BACKGROUND = [119, 119, 119]  # neutral mid gray surround, about OKLab L 0.6

PRIMARIES = [
    ("red", (1, 0, 0)),
    ("green", (0, 1, 0)),
    ("blue", (0, 0, 1)),
    ("cyan", (0, 1, 1)),
    ("magenta", (1, 0, 1)),
    ("yellow", (1, 1, 0)),
]


def _colorchecker_srgb8() -> list[tuple[str, list[int]]]:
    """ColorChecker 24 (after Nov 2014) in 8-bit sRGB, computed by colour-science.

    The reference data is xyY under D50; it is adapted to D65 with Bradford and
    encoded to sRGB. Cyan is slightly outside sRGB and gets clipped.
    """
    cc = colour.CCS_COLOURCHECKERS["ColorChecker24 - After November 2014"]
    xyz = colour.xyY_to_XYZ(np.array(list(cc.data.values())))
    rgb = colour.XYZ_to_RGB(
        xyz,
        "sRGB",
        illuminant=cc.illuminant,
        chromatic_adaptation_transform="Bradford",
        apply_cctf_encoding=True,
    )
    rgb8 = np.round(np.clip(rgb, 0, 1) * 255).astype(int)
    return [(name, v.tolist()) for name, v in zip(cc.data, rgb8, strict=True)]


def make_chart() -> tuple[npt.NDArray[np.uint8], dict[str, Any]]:
    """Draw the chart and return (pixels, layout).

    Layout lists every flat patch with its rectangle and exact 8-bit value,
    so a QA script can measure the same patches in any app's export.
    """
    img = np.empty((CHART_H, CHART_W, 3), dtype=np.uint8)
    img[:] = BACKGROUND
    patches: list[dict[str, Any]] = []

    def patch(name: str, group: str, x: int, y: int, w: int, h: int, rgb8: list[int]):
        img[y : y + h, x : x + w] = rgb8
        patches.append(
            {"name": name, "group": group, "x": x, "y": y, "w": w, "h": h, "rgb8": rgb8}
        )

    # Gray ramp: 33 steps, the same count as the LUT grid.
    steps = np.round(np.linspace(0, 255, 33)).astype(int)
    w, x0 = 36, (CHART_W - 33 * 36) // 2
    for i, v in enumerate(steps):
        patch(f"gray {i:02d}", "gray", x0 + i * w, 40, w, 80, [int(v)] * 3)

    # ColorChecker 24, 6 columns x 4 rows.
    size, gap = 120, 16
    x0 = (CHART_W - (6 * size + 5 * gap)) // 2
    for i, (name, rgb8) in enumerate(_colorchecker_srgb8()):
        row, col = divmod(i, 6)
        x, y = x0 + col * (size + gap), 160 + row * (size + gap)
        patch(name, "colorchecker", x, y, size, size, rgb8)

    # Primaries and secondaries at full and half strength.
    size = 80
    x0 = (CHART_W - (12 * size + 11 * gap)) // 2
    for i, (name, rgb) in enumerate(PRIMARIES):
        for j, (label, level) in enumerate([("100%", 255), ("50%", 128)]):
            x = x0 + (2 * i + j) * (size + gap)
            patch(
                f"{name} {label}",
                "primary",
                x,
                724,
                size,
                size,
                [c * level for c in rgb],
            )

    # Smooth strips for checking banding by eye (not measured).
    ramp = np.linspace(0, 1, 1200)
    img[840:900, 40:1240] = np.round(ramp * 255).astype(np.uint8)[None, :, None]
    hue = np.stack([ramp, np.ones_like(ramp), np.ones_like(ramp)], axis=-1)
    img[920:980, 40:1240] = np.round(colour.HSV_to_RGB(hue) * 255).astype(np.uint8)
    strips = [
        {"name": "gray gradient", "x": 40, "y": 840, "w": 1200, "h": 60},
        {"name": "hue sweep", "x": 40, "y": 920, "w": 1200, "h": 60},
    ]

    layout = {
        "version": 1,
        "description": "lookmatch test chart, 8-bit sRGB. Patch values are exact.",
        "size": [CHART_W, CHART_H],
        "background": BACKGROUND,
        "patches": patches,
        "strips": strips,
    }
    return img, layout


def main() -> None:
    """Write test_look_33.cube, test_chart.png and test_chart.json."""
    write_cube(HERE / "test_look_33.cube", make_test_look())
    pixels, layout = make_chart()
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.fromarray(pixels).save(HERE / "test_chart.png", icc_profile=srgb)
    (HERE / "test_chart.json").write_text(json.dumps(layout, indent=1) + "\n")
    print("Wrote test_look_33.cube, test_chart.png, test_chart.json")


if __name__ == "__main__":
    main()
