"""Generate the README figures from real lookmatch output.

Run from the repo root:

    .venv/bin/python docs/figures/make_figures.py

Every number in these figures is computed by lookmatch itself. Each chart is
written twice, for GitHub's light and dark themes.
"""

import re
import sys
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import numpy.typing as npt  # noqa: E402
import rawpy  # noqa: E402
from PIL import Image, ImageOps  # noqa: E402

from lookmatch import io  # noqa: E402
from lookmatch.apply import apply_lut  # noqa: E402
from lookmatch.metrics import delta_e_2000  # noqa: E402
from lookmatch.pipeline import fit  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
sys.path.insert(0, str(ROOT / "bench"))
import make_fixtures  # noqa: E402
import make_looks  # noqa: E402

FONT_STACK = "-apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif"

# Tokens per theme. The two series colors pass the dataviz palette checker
# (CVD and contrast) on both surfaces; each line also has a direct text label.
THEMES = {
    "light": {
        "text": "#1d1d1f",
        "muted": "#6e6e73",
        "grid": "#e5e5ea",
        "zero": "#86868b",
        "card": "#f5f5f7",
        "accent": "#0071e3",
        "lightness": "#2a78d6",
        "warmth": "#eb6834",
    },
    "dark": {
        "text": "#f5f5f7",
        "muted": "#a1a1a6",
        "grid": "#3a3a3c",
        "zero": "#86868b",
        "card": "#1c1c1e",
        "accent": "#2997ff",
        "lightness": "#3987e5",
        "warmth": "#d95926",
    },
}


def _svg_fonts(path: Path) -> None:
    """Swap matplotlib's single font name for a system font stack."""
    text = path.read_text()
    text = re.sub(r"font-family:[^;\"]*", f"font-family:{FONT_STACK}", text)
    text = re.sub(r'font-family="[^"]*"', f'font-family="{FONT_STACK}"', text)
    path.write_text(text)


# --- Figure: what the test look does to a gray ramp -----------------------------


def tone_response(theme: str) -> Path:
    """Plot how the test LUT changes lightness and warmth along a gray ramp.

    The ramp goes through apply_lut, and both input and output are measured
    in OKLab: lightness is L, warmth is b (positive = yellow/warm,
    negative = blue/cool). Both are OKLab coordinates, so they share one axis.
    """
    t = THEMES[theme]
    look = make_fixtures.make_test_look()
    levels = np.arange(256)
    gray = np.repeat((levels / 255.0)[:, None], 3, axis=1)
    lab_in = io.srgb_to_oklab(gray)
    lab_out = io.srgb_to_oklab(apply_lut(gray, look))
    lightness = (lab_out[:, 0] - lab_in[:, 0]) * 100
    warmth = (lab_out[:, 2] - lab_in[:, 2]) * 100

    plt.rcParams.update(
        {
            "svg.fonttype": "none",
            "svg.hashsalt": "lookmatch",  # same internal IDs on every run
            "font.family": "Helvetica Neue",
            "font.size": 11,
        }
    )
    fig, ax = plt.subplots(figsize=(8.8, 3.8), dpi=100)
    fig.subplots_adjust(left=0.09, right=0.97, top=0.80, bottom=0.16)

    ax.axhline(0, color=t["zero"], linewidth=1)
    ax.axvspan(0, 96, color=t["card"], zorder=0)
    ax.axvspan(160, 255, color=t["card"], zorder=0)
    series = [
        ("Warmth (OKLab b)", warmth, t["warmth"], 52),
        ("Lightness (OKLab L)", lightness, t["lightness"], 200),
    ]
    for name, values, color, at in series:
        ax.plot(levels, values, color=color, linewidth=2, label=name)
        ax.annotate(
            name.split(" (")[0],
            (levels[at], values[at]),
            xytext=(0, 8 if values[at] >= 0 else -16),
            textcoords="offset points",
            ha="center",
            color=t["text"],
            fontsize=10,
        )

    ax.text(48, -4.6, "Shadows: warmer, darker", color=t["muted"], ha="center")
    ax.text(207, -4.6, "Highlights: cooler, brighter", color=t["muted"], ha="center")

    ax.set_xlim(0, 255)
    ax.set_ylim(-5.2, 5.2)
    ax.set_xticks([0, 64, 128, 192, 255])
    ax.set_xlabel("Input gray level (8-bit)", color=t["muted"])
    ax.set_ylabel("Change (OKLab x 100)", color=t["muted"])
    ax.grid(axis="y", color=t["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors=t["muted"], length=0)

    fig.text(
        0.09, 0.93, "Test look, measured on a gray ramp", color=t["text"],
        fontsize=14, fontweight="bold",
    )  # fmt: skip
    legend = ax.legend(
        loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3, frameon=False,
        handlelength=1.6, fontsize=10,
    )  # fmt: skip
    for text in legend.get_texts():
        text.set_color(t["text"])

    path = OUT / f"tone_response_{theme}.svg"
    fig.savefig(path, transparent=True, metadata={"Date": None})  # no timestamp
    plt.close(fig)
    _svg_fonts(path)
    return path


# --- Figure: the test chart before and after the test look ---------------------


def chart_before_after() -> Path:
    """Show the test chart and the same chart with the test LUT applied."""
    pixels, _ = make_fixtures.make_chart()
    before = pixels.astype(np.float32) / 255.0
    after = apply_lut(before, make_fixtures.make_test_look())
    gap = np.full((before.shape[0], 32, 3), 1.0, dtype=np.float32)
    both = np.concatenate([before, gap, after], axis=1)
    img = Image.fromarray(np.round(both * 255).astype(np.uint8))
    img = img.resize((img.width // 2, img.height // 2), Image.Resampling.LANCZOS)
    path = OUT / "chart_before_after.png"
    img.save(path, optimize=True)
    return path


# --- Figure: lookmatch learning a look from photos -----------------------------

# The maintainer's own photos, approved for demos (landscapes, no people).
DEMO_DIR = Path("/Users/jingrui_feng/Pictures/2026/2026-08-30")
DEMO_PHOTOS = ["DSC08255", "DSC08549", "DSC08606"]
DEMO_SHOWN = "DSC08255"
DEMO_LOOK = "teal_orange"


def _camera_jpeg(name: str) -> npt.NDArray[np.float32]:
    """Return the camera's own JPEG rendering of a demo RAW, 640 px long side."""
    with rawpy.imread(str(DEMO_DIR / f"{name}.ARW")) as raw:
        jpeg = raw.extract_thumb().data
    photo = ImageOps.exif_transpose(Image.open(BytesIO(jpeg))).convert("RGB")
    photo.thumbnail((640, 640), Image.Resampling.LANCZOS)
    return np.asarray(photo, dtype=np.float32) / 255.0


def photo_match() -> Path | None:
    """Show your photo, the target look, and the look lookmatch learned.

    A known look (teal_orange from the benchmark) is applied to the three
    demo photos to make the references. lookmatch then learns the look from
    those references and the original photos, with its default settings.
    This is the same-scenes case: the references show the same scenes as
    the inputs. Prints the ΔE 2000 numbers quoted in the README. Skipped if
    the RAW files aren't on disk.
    """
    if not all((DEMO_DIR / f"{n}.ARW").is_file() for n in DEMO_PHOTOS):
        print(f"Skipping photo figure: demo photos not found in {DEMO_DIR}")
        return None
    look = make_looks.make_look(DEMO_LOOK)
    photos = {n: _camera_jpeg(n) for n in DEMO_PHOTOS}
    with TemporaryDirectory() as tmp:
        refs, mine = Path(tmp, "refs"), Path(tmp, "mine")
        refs.mkdir()
        mine.mkdir()
        for name, image in photos.items():
            _save_png(refs / f"{name}.png", apply_lut(image, look))
            _save_png(mine / f"{name}.png", image)
        learned = fit(refs, mine, name="learned").cube

    for name, image in photos.items():
        target = apply_lut(image, look)
        look_size = delta_e_2000(image, target).mean()
        miss = delta_e_2000(apply_lut(image, learned), target).mean()
        print(
            f"  {name}: target vs original ΔE {look_size:.2f}, vs lookmatch {miss:.2f}"
        )

    shown = photos[DEMO_SHOWN]
    panels = [shown, apply_lut(shown, look), apply_lut(shown, learned)]
    gap = np.full((shown.shape[0], 16, 3), 1.0, dtype=np.float32)
    row = np.concatenate([panels[0], gap, panels[1], gap, panels[2]], axis=1)
    path = OUT / "photo_match.jpg"
    Image.fromarray(np.round(np.clip(row, 0, 1) * 255).astype(np.uint8)).save(
        path, quality=88, optimize=True
    )
    return path


def _save_png(path: Path, srgb: npt.ArrayLike) -> None:
    pixels = np.round(np.clip(np.asarray(srgb), 0, 1) * 255).astype(np.uint8)
    Image.fromarray(pixels).save(path)


# --- Figure: the pipeline --------------------------------------------------------

STEPS = [
    ("1", "Load", ["sRGB, linear and OKLab", "100,000 pixels per photo", "fixed seed"]),
    ("2", "Neutralize", ["white balance", "exposure", "per photo, then pooled"]),
    ("3", "Measure the look", ["tone curve (isotonic)", "split toning (WLS)", "sliced optimal transport"]),  # noqa: E501
    ("4", "Bake", ["33-point 3D LUT", "least squares + smoothness", "skin hue guard"]),
    ("5", "Verify", ["distribution distance", "skin hue drift, SSIM", "warnings in plain words"]),  # noqa: E501
    ("6", "Export", [".cube, Hald PNG", "Lightroom preset", "report.html"]),
]  # fmt: skip


def pipeline(theme: str) -> Path:
    """Draw the six pipeline steps as cards in two rows of three."""
    t = THEMES[theme]
    w, h = 880, 400
    cw, ch, gx, gy = 256, 150, 56, 36
    x0, y0 = (w - (3 * cw + 2 * gx)) // 2, 62
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="{FONT_STACK}">',
        f'<text x="{x0}" y="32" font-size="18" font-weight="600" fill="{t["text"]}">'
        "How lookmatch builds a look</text>",
    ]
    for i, (num, title, lines) in enumerate(STEPS):
        row, col = divmod(i, 3)
        x, y = x0 + col * (cw + gx), y0 + row * (ch + gy)
        parts.append(
            f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="18" '
            f'fill="{t["card"]}"/>'
        )
        parts.append(
            f'<text x="{x + 24}" y="{y + 38}" font-size="13" font-weight="600" '
            f'fill="{t["accent"]}">STEP {num}</text>'
        )
        parts.append(
            f'<text x="{x + 24}" y="{y + 64}" font-size="19" font-weight="600" '
            f'fill="{t["text"]}">{title}</text>'
        )
        for j, line in enumerate(lines):
            parts.append(
                f'<text x="{x + 24}" y="{y + 92 + j * 20}" font-size="13.5" '
                f'fill="{t["muted"]}">{line}</text>'
            )
        if col < 2:  # arrow to the next card in the row
            ax, ay = x + cw + 14, y + ch // 2
            parts.append(
                f'<path d="M{ax} {ay} h{gx - 28} m-6 -5 l6 5 l-6 5" fill="none" '
                f'stroke="{t["muted"]}" stroke-width="1.6" stroke-linecap="round" '
                'stroke-linejoin="round"/>'
            )
    # Arrow from the end of row one down to the start of row two.
    ex, ey = x0 + 2 * (cw + gx) + cw // 2, y0 + ch + 6
    sx = x0 + cw // 2
    parts.append(
        f'<path d="M{ex} {ey} v{gy // 2 - 6} H{sx} v{gy // 2 - 6} m-5 -6 l5 6 l5 -6" '
        f'fill="none" stroke="{t["muted"]}" stroke-width="1.6" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    )
    parts.append("</svg>")
    path = OUT / f"pipeline_{theme}.svg"
    path.write_text("\n".join(parts) + "\n")
    return path


def main() -> None:
    """Write every README figure."""
    written = [chart_before_after()]
    photo = photo_match()
    if photo is not None:
        written.append(photo)
    for theme in THEMES:
        written += [tone_response(theme), pipeline(theme)]
    for path in written:
        print(f"Wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
