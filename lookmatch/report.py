"""report.html: one self-contained page that shows what a run did.

The page has no outside dependencies: previews are embedded as JPEG data,
the tone curve is drawn as inline SVG, and it uses the system font. It opens
offline, can be emailed as one file, and works on a phone. It follows the
light or dark setting of the device.

Sections: the look's name and summary, warnings, before and after previews
of your photos, what the look does (tone curve and split toning in plain
words), the measurements, the files written, and the settings needed to
reproduce the run.
"""

import base64
import io as stdlib_io
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from jinja2 import Environment, PackageLoader, select_autoescape
from PIL import Image

from lookmatch import __version__, io, metrics, toning
from lookmatch.apply import apply_lut
from lookmatch.checks import MIN_SKIN_FRACTION
from lookmatch.export.cube import Cube
from lookmatch.look import Look

PREVIEW_SIDE = 1600  # long side of each preview, pixels
EMBED_SIDE = 900  # long side of the copies embedded in report.html
MAX_PREVIEWS = 12  # previews shown in the report
JPEG_QUALITY = 85

Uint8Image = npt.NDArray[np.uint8]


@dataclass(frozen=True)
class Preview:
    """One of your photos before and after the look, at preview size."""

    name: str
    before: Uint8Image
    after: Uint8Image
    ssim: float  # structure kept, 1 = untouched (metrics.ssim_lightness)


def _to_uint8(srgb: npt.ArrayLike) -> Uint8Image:
    scaled = np.round(np.clip(np.asarray(srgb, dtype=np.float64), 0.0, 1.0) * 255.0)
    return np.asarray(scaled, dtype=np.uint8)


def make_previews(
    photos: Sequence[str | Path], cube: Cube, max_side: int = PREVIEW_SIDE
) -> list[Preview]:
    """Apply a look to each photo at preview size, and measure SSIM.

    Photos are read one at a time and never modified.
    """
    previews = []
    for path in photos:
        im = Image.fromarray(_to_uint8(io.load_image(path)))
        im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        before = np.asarray(im, dtype=np.float32) / 255.0
        after = apply_lut(before, cube)
        previews.append(
            Preview(
                name=Path(path).name,
                before=np.asarray(im, dtype=np.uint8),
                after=_to_uint8(after),
                ssim=metrics.ssim_lightness(before, after),
            )
        )
    return previews


def preview_metrics(previews: Sequence[Preview]) -> dict[str, float]:
    """Return the SSIM summary for look.json: mean and lowest over previews."""
    if not previews:
        return {}
    values = [p.ssim for p in previews]
    return {"ssim_mean": float(np.mean(values)), "ssim_min": float(np.min(values))}


def _data_uri(image: Uint8Image) -> str:
    im = Image.fromarray(image)
    im.thumbnail((EMBED_SIDE, EMBED_SIDE), Image.Resampling.LANCZOS)
    buffer = stdlib_io.BytesIO()
    im.save(buffer, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


# --- The look in plain words ---------------------------------------------------

# OKLCh hue angles of familiar color names (Ottosson 2020; approximate).
_HUE_NAMES = [
    (25.0, "red"),
    (55.0, "orange"),
    (100.0, "yellow"),
    (140.0, "green"),
    (185.0, "teal"),
    (245.0, "blue"),
    (300.0, "purple"),
    (345.0, "pink"),
]
# OKLab chroma of a tint: below 0.005 it is hard to see.
_STRENGTHS = [(0.005, "none"), (0.015, "subtle"), (0.03, "moderate")]
_ZONE_LIGHTNESS = {"shadows": 0.25, "midtones": 0.6, "highlights": 0.9}
_ZONE_LABELS = {
    "shadows": "Shadows",
    "midtones": "Midtones",
    "highlights": "Highlights",
}


def hue_name(degrees: float) -> str:
    """Return the nearest familiar color name for an OKLCh hue angle."""

    def distance(entry: tuple[float, str]) -> float:
        return abs((degrees - entry[0] + 180.0) % 360.0 - 180.0)

    return min(_HUE_NAMES, key=distance)[1]


def strength_name(chroma: float) -> str:
    """Return none, subtle, moderate or strong for a tint's OKLab chroma."""
    for limit, name in _STRENGTHS:
        if chroma < limit:
            return name
    return "strong"


def _css(lab: tuple[float, float, float]) -> str:
    r, g, b = _to_uint8(io.oklab_to_srgb(np.array(lab)))
    return f"rgb({r}, {g}, {b})"


def toning_rows(split: toning.SplitToning | None) -> list[dict[str, str]]:
    """Describe the tint at each zone's brightness, with a color swatch.

    The zone offsets blend into each other (see toning.py), so the tint
    actually added at a brightness is shown, not the zone's own offset.
    """
    split = split or toning.SplitToning()
    rows = []
    for zone in toning.ZONES:
        lightness = _ZONE_LIGHTNESS[zone]
        neutral = np.array([[lightness, 0.0, 0.0]])
        a, b = toning.apply_split_toning(neutral, split)[0, 1:]
        chroma = float(np.hypot(a, b))
        hue = float(np.degrees(np.arctan2(b, a)) % 360.0)
        strength = strength_name(chroma)
        rows.append(
            {
                "zone": _ZONE_LABELS[zone],
                "words": "No tint"
                if strength == "none"
                else f"{strength.capitalize()} {hue_name(hue)}",
                "neutral": _css((lightness, 0.0, 0.0)),
                "tinted": _css((lightness, float(a), float(b))),
            }
        )
    return rows


def tone_curve_svg(curve: Sequence[float] | None) -> str:
    """Draw the tone curve as inline SVG that follows the page's colors."""
    size, pad = 240.0, 0.0
    values = np.asarray(curve if curve is not None else np.linspace(0, 1, 256))
    xs = np.linspace(0.0, 1.0, values.size)
    points = " ".join(
        f"{pad + x * size:.1f},{pad + (1.0 - y) * size:.1f}"
        for x, y in zip(xs, values, strict=True)
    )
    grid = "".join(
        f'<line class="grid" x1="{t * size:.0f}" y1="0" x2="{t * size:.0f}" '
        f'y2="{size:.0f}"/><line class="grid" x1="0" y1="{t * size:.0f}" '
        f'x2="{size:.0f}" y2="{t * size:.0f}"/>'
        for t in (0.25, 0.5, 0.75)
    )
    return (
        f'<svg viewBox="0 0 {size:.0f} {size:.0f}" role="img" '
        'aria-label="Tone curve: how the look maps brightness from your photo '
        '(across) to the result (up). The dashed diagonal means no change.">'
        f'<rect class="frame" x="0" y="0" width="{size:.0f}" height="{size:.0f}"/>'
        f"{grid}"
        f'<line class="diagonal" x1="0" y1="{size:.0f}" x2="{size:.0f}" y2="0"/>'
        f'<polyline class="curve" points="{points}"/></svg>'
    )


def scene_words(match: float | None, copied: float | None) -> str:
    """Describe the scene match in a few words."""
    if copied:
        return "Same photos"
    if match is None:
        return "Not measured"
    if match >= 0.8:
        return "Same kind of scenes"
    if match >= 0.5:
        return "Similar scenes"
    return "Different scenes"


def _closer(before: float | None, after: float | None) -> str:
    if before is None or after is None or before <= 0:
        return "Not measured"
    change = 1.0 - after / before
    if change <= 0:
        return "No closer"
    return f"{change:.0%} closer"


def measurement_rows(look: Look) -> list[dict[str, str]]:
    """List the measurements, each with a plain reading and explanation."""
    m = look.metrics
    rows = [
        {
            "name": "Colors",
            "value": _closer(
                m.get("color_distance_before"), m.get("color_distance_after")
            ),
            "note": "How much closer your photos' colors came to the "
            "references' colors, overall.",
        },
        {
            "name": "Brightness",
            "value": _closer(
                m.get("lightness_distance_before"), m.get("lightness_distance_after")
            ),
            "note": "How much closer your photos' brightness came to the references'.",
        },
        {
            "name": "Scenes",
            "value": scene_words(
                m.get("scene_match"), m.get("references_copied_from_inputs")
            ),
            "note": "How alike your photos and the references are. The more "
            "alike, the more of the look lookmatch can safely learn.",
        },
    ]
    if m.get("skin_fraction", 0.0) >= MIN_SKIN_FRACTION:
        rows.append(
            {
                "name": "Skin tones",
                "value": f"Up to {m.get('skin_hue_drift_p95', 0.0):.0f}° hue shift",
                "note": "How far the look turns skin-colored areas toward "
                "orange, pink or green. Up to about 6° looks natural.",
            }
        )
    if "ssim_mean" in m:
        rows.append(
            {
                "name": "Picture quality",
                "value": f"{m['ssim_mean']:.3f} kept (lowest {m['ssim_min']:.3f})",
                "note": "Whether the look damaged detail, for example with "
                "banding or noise. 1 means untouched; a strong look lowers it "
                "a little.",
            }
        )
    return rows


# --- Rendering -------------------------------------------------------------------


def _environment() -> Environment:
    return Environment(
        loader=PackageLoader("lookmatch", "templates"),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_report(
    look: Look,
    previews: Sequence[Preview] = (),
    files: Sequence[str] = (),
) -> str:
    """Return report.html for a fitted look as one HTML string."""
    refs = [p for p in look.photos if p.role == "reference"]
    mine = [p for p in look.photos if p.role == "input"]
    shown = list(previews)[:MAX_PREVIEWS]
    context: dict[str, Any] = {
        "look": look,
        "version": __version__,
        "reference_count": len(refs),
        "input_count": len(mine),
        "rendering": "RAW files decoded by lookmatch"
        if any(p.source == "raw" for p in mine)
        else "Exports from your editor",
        "scene": scene_words(
            look.metrics.get("scene_match"),
            look.metrics.get("references_copied_from_inputs"),
        ),
        "portrait": bool(look.settings.get("portrait")),
        "previews": [
            {"name": p.name, "before": _data_uri(p.before), "after": _data_uri(p.after)}
            for p in shown
        ],
        "more_previews": max(0, len(previews) - len(shown)),
        "curve_svg": tone_curve_svg(look.tone_curve),
        "toning": toning_rows(look.split_toning),
        "measurements": measurement_rows(look),
        "files": list(files),
        "details": sorted(look.metrics.items()),
        "settings": sorted(look.settings.items()),
    }
    return _environment().get_template("report.html").render(**context)


def write_report(
    path: str | Path,
    look: Look,
    previews: Sequence[Preview] = (),
    files: Sequence[str] = (),
) -> Path:
    """Write report.html and return its path."""
    path = Path(path)
    path.write_text(render_report(look, previews, files), encoding="utf-8")
    return path
