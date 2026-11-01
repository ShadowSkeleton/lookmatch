"""Lightroom / Camera Raw XMP preset export.

The preset carries the look's tone curve and split toning as Lightroom point
curves, so a photographer can see and adjust them in the Tone Curve panel:

- The master point curve (crs:ToneCurvePV2012) holds the tone curve. On gray
  tones it does exactly what the LUT does: a gray of a given sRGB value has
  the same encoded value in Lightroom's curve space (ProPhoto primaries with
  the sRGB tone response, which Adobe calls Melissa RGB), whatever the
  primaries, so the gray-to-gray mapping carries over unchanged.
- The red, green and blue point curves hold the split toning: on gray tones
  they turn each gray into the tinted color the LUT gives it, converted to
  Lightroom's curve space (sRGB to ProPhoto primaries, Bradford adaptation
  from D65 to D50, sRGB tone response). They are fitted assuming Lightroom
  applies the channel curves after the master curve.

The preset is an approximation: point curves act on each color channel, so
they change saturated colors differently from the LUT, and the LUT's
color-by-color corrections (sliced optimal transport) can't be expressed as
curves at all. The Lightroom profile (LIGHTROOM_PROFILE.md) carries the exact
LUT; the preset is for photographers who want sliders they can edit.

The Color Grading wheels are not used: how a wheel's saturation number maps
to an amount of tint isn't published, and lookmatch never guesses a number.

Every field name and format here is copied from a preset saved by Lightroom
Classic (tests/fixtures/lr_preset_reference.xmp), never guessed.
"""

import hashlib
from collections.abc import Callable, Sequence
from pathlib import Path
from xml.sax.saxutils import escape

import colour
import numpy as np
import numpy.typing as npt

from lookmatch import io, tone, toning
from lookmatch.look import Look

# Values copied from tests/fixtures/lr_preset_reference.xmp.
CRS_VERSION = "14.2"
PROCESS_VERSION = "11.0"

MAX_POINTS = 16  # points per curve
TOLERANCE = 0.5  # levels (out of 255) a curve may miss its target by
MIN_GAP = 4  # levels between points, so Lightroom's smooth curve can't wobble
GROUP = "lookmatch"

FloatArray = npt.NDArray[np.float64]
Points = list[tuple[int, int]]

# sRGB to ProPhoto RGB primaries, Bradford adaptation (D65 to D50). Each row
# is scaled to add up to 1 so that gray stays exactly gray.
_TO_PROPHOTO = colour.matrix_RGB_to_RGB(
    colour.RGB_COLOURSPACES["sRGB"],
    colour.RGB_COLOURSPACES["ProPhoto RGB"],
    chromatic_adaptation_transform="Bradford",
)
_TO_PROPHOTO = _TO_PROPHOTO / _TO_PROPHOTO.sum(axis=1, keepdims=True)

_SAMPLES = 1024  # gray levels sampled to fit the curves
_LEVELS = np.arange(256, dtype=np.float64)


def _gray_targets(look: Look) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Return gray inputs, their toned gray, and their tinted color.

    All three in Lightroom's curve space, 0 to 1: input gray value, output
    gray value after the tone curve, and output (r, g, b) after split toning.
    """
    v = np.linspace(0.0, 1.0, _SAMPLES)
    lightness = io.srgb_to_oklab(np.stack([v, v, v], axis=-1))[:, 0]
    curve = look.tone_curve if look.tone_curve is not None else tone.GRID
    toned = tone.apply_tone_curve(lightness, curve)
    zeros = np.zeros_like(toned)
    gray = np.stack([toned, zeros, zeros], axis=-1)
    tinted = toning.apply_split_toning(gray, look.split_toning or toning.SplitToning())
    toned_gray = np.clip(io.oklab_to_srgb(gray)[:, 0], 0.0, 1.0)
    linear = np.clip(io.oklab_to_linear_srgb(tinted), 0.0, 1.0)
    prophoto = np.clip(io.linear_to_srgb(linear @ _TO_PROPHOTO.T), 0.0, 1.0)
    return v, toned_gray.astype(np.float64), prophoto.astype(np.float64)


def _on_levels(x: FloatArray, y: FloatArray) -> FloatArray:
    """Resample a monotonic curve given at points x to the 256 input levels.

    Beyond the range of x (levels no photo reaches, for example above the
    master curve's white point), the curve continues at slope 1, which keeps
    it smooth instead of bending flat.
    """
    x255, y255 = x * 255.0, np.maximum.accumulate(y) * 255.0
    ux, inverse = np.unique(x255, return_inverse=True)
    uy = np.bincount(inverse, weights=y255) / np.bincount(inverse)
    out = np.interp(_LEVELS, ux, uy)
    out = np.where(_LEVELS < ux[0], _LEVELS - ux[0] + uy[0], out)
    out = np.where(_LEVELS > ux[-1], _LEVELS - ux[-1] + uy[-1], out)
    return np.asarray(np.clip(out, 0.0, 255.0), dtype=np.float64)


def curve_points(
    target: FloatArray,
    max_points: int = MAX_POINTS,
    tolerance: float = TOLERANCE,
    min_gap: int = MIN_GAP,
) -> Points:
    """Pick point-curve points that follow a 256-level target curve.

    Greedy: start from the two ends and keep adding the level where straight
    lines between the points miss the target most (at least ``min_gap``
    levels from every point so far), until every level is within
    ``tolerance`` or there are ``max_points``. Lightroom draws a smooth curve
    through the points, which follows a smooth target at least as well.
    Returns integer (input, output) pairs, 0 to 255, never going down.
    """
    target = np.clip(np.asarray(target, dtype=np.float64), 0.0, 255.0)
    if target.shape != (256,):
        raise ValueError(f"A curve target needs 256 levels, got {target.shape}.")
    chosen = [0, 255]
    while len(chosen) < max_points:
        xs = np.array(chosen, dtype=np.float64)
        error = np.abs(np.interp(_LEVELS, xs, target[chosen]) - target)
        near = np.min(np.abs(_LEVELS[:, None] - xs[None, :]), axis=1) < min_gap
        error[near] = 0.0
        worst = int(np.argmax(error))
        if error[worst] <= tolerance:
            break
        chosen = sorted([*chosen, worst])
    ys = np.maximum.accumulate(np.round(target[chosen]).astype(int))
    return [(x, int(y)) for x, y in zip(chosen, ys, strict=True)]


def preset_curves(look: Look) -> dict[str, Points]:
    """Return the four point curves (master, red, green, blue) for a look."""
    v, toned, tinted = _gray_targets(look)
    curves = {"master": curve_points(_on_levels(v, toned))}
    for i, channel in enumerate(("red", "green", "blue")):
        # Channel curves act on the master curve's output.
        curves[channel] = curve_points(_on_levels(toned, tinted[:, i]))
    return curves


def _seq(points: Sequence[tuple[int, int]], indent: str) -> str:
    items = "".join(f"{indent} <rdf:li>{x}, {y}</rdf:li>\n" for x, y in points)
    return f"{indent}<rdf:Seq>\n{items}{indent}</rdf:Seq>\n"


def _alt(text: str, indent: str) -> str:
    if not text:
        return (
            f'{indent}<rdf:Alt>\n{indent} <rdf:li xml:lang="x-default"/>\n'
            f"{indent}</rdf:Alt>\n"
        )
    return (
        f'{indent}<rdf:Alt>\n{indent} <rdf:li xml:lang="x-default">'
        f"{escape(text)}</rdf:li>\n{indent}</rdf:Alt>\n"
    )


def _uuid(text: str) -> str:
    """Return a stable 32-digit preset ID: the same look gets the same ID."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32].upper()


def _description(look: Look) -> str:
    refs = sum(p.role == "reference" for p in look.photos)
    mine = sum(p.role == "input" for p in look.photos)
    return (
        f"Made by lookmatch from {refs} reference photos and {mine} of your "
        "photos. Tone curve and split toning only; the matching profile "
        "carries the full look."
    )


def format_preset(look: Look) -> str:
    """Return the XMP preset text for a look."""
    curves = preset_curves(look)
    blocks: list[tuple[str, Callable[[str], str]]] = [
        ("Name", lambda i: _alt(look.name, i)),
        ("ShortName", lambda i: _alt("", i)),
        ("SortName", lambda i: _alt("", i)),
        ("Group", lambda i: _alt(GROUP, i)),
        ("Description", lambda i: _alt(_description(look), i)),
        ("ToneCurvePV2012", lambda i: _seq(curves["master"], i)),
        ("ToneCurvePV2012Red", lambda i: _seq(curves["red"], i)),
        ("ToneCurvePV2012Green", lambda i: _seq(curves["green"], i)),
        ("ToneCurvePV2012Blue", lambda i: _seq(curves["blue"], i)),
    ]
    body = "".join(
        f"   <crs:{tag}>\n{block('    ')}   </crs:{tag}>\n" for tag, block in blocks
    )
    uuid = _uuid(look.name + repr(sorted(curves.items())))
    attributes = {
        "PresetType": "Normal",
        "Cluster": "",
        "UUID": uuid,
        "SupportsAmount": "True",
        "SupportsColor": "True",
        "SupportsMonochrome": "True",
        "SupportsHighDynamicRange": "True",
        "SupportsNormalDynamicRange": "True",
        "SupportsSceneReferred": "True",
        "SupportsOutputReferred": "True",
        "RequiresRGBTables": "False",
        "CameraModelRestriction": "",
        "Copyright": "",
        "ContactInfo": "",
        "Version": CRS_VERSION,
        "ProcessVersion": PROCESS_VERSION,
        "ToneCurveName2012": "Custom",
        "HasSettings": "True",
    }
    attrs = "\n".join(f'   crs:{k}="{v}"' for k, v in attributes.items())
    return (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="lookmatch">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '  <rdf:Description rdf:about=""\n'
        '    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"\n'
        f"{attrs}>\n"
        f"{body}"
        "  </rdf:Description>\n"
        " </rdf:RDF>\n"
        "</x:xmpmeta>\n"
    )


def write_preset(path: str | Path, look: Look) -> None:
    """Write a look as a Lightroom / Camera Raw .xmp preset (UTF-8)."""
    Path(path).write_text(format_preset(look), encoding="utf-8", newline="\n")
