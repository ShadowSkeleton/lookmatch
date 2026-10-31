"""Warnings: problems a run found, in plain words, with what to do next.

Each warning has a stable code (for programs and the agent layer) and a
message written for a photographer. check() reads only what the fitted Look
records (photos, settings and metrics), so a look.json can be checked again
later without the photos.

Codes:

- scenes_differ: your photos and the references show different scenes, so
  only the safe part of the look was learned.
- skin_drift: skin-colored areas change hue more than SKIN_DEGREES.
- skin_protected: portrait mode held back a skin hue change.
- reference_small: a reference photo is smaller than MIN_SHORT_SIDE.
- reference_compressed: a reference JPEG is heavily compressed.
- few_inputs: fewer than MIN_INPUTS of your photos.
- raw_inputs: your photos were decoded from RAW by lookmatch.
- mixed_inputs: your photos mix RAW files and exports.

Not checked yet: whether the reference photos share one look. The obvious
measure, how much the tint differs from photo to photo, turned out to depend
more on scene content than on the look (docs/method.md).
"""

from lookmatch.look import Look, LookWarning, Photo
from lookmatch.skin import MAX_DRIFT_DEGREES

MIN_SCENE_MATCH = 0.5  # below this, only the safe part of the look is used
SKIN_DEGREES = MAX_DRIFT_DEGREES
MIN_SKIN_FRACTION = 0.02  # less skin-colored area than this isn't judged
MIN_SHORT_SIDE = 800  # pixels
MIN_JPEG_QUALITY = 70
MIN_INPUTS = 5


def _names(photos: list[Photo], limit: int = 3) -> str:
    names = [p.file for p in photos]
    shown = ", ".join(names[:limit])
    return shown if len(names) <= limit else f"{shown} and {len(names) - limit} more"


def _scenes(look: Look) -> list[LookWarning]:
    match = look.metrics.get("scene_match")
    if match is None or match >= MIN_SCENE_MATCH:
        return []
    return [
        LookWarning(
            "scenes_differ",
            f"Your photos and the reference photos show quite different scenes "
            f"(scene match {match:.0%}). lookmatch learned only the parts of the "
            "look that hold up across different scenes: how deep the blacks and "
            "how bright the whites are, and the overall color tint. Changes to "
            "contrast and saturation were left out, because they can't be told "
            "apart from what the scenes show. For a closer match, use reference "
            "photos of scenes like yours.",
        )
    ]


def _skin(look: Look) -> list[LookWarning]:
    fraction = look.metrics.get("skin_fraction", 0.0)
    drift = look.metrics.get("skin_hue_drift_p95", 0.0)
    held = look.metrics.get("skin_hue_drift_p95_unprotected")
    if fraction < MIN_SKIN_FRACTION:
        return []
    if look.settings.get("portrait"):
        if held is None or held <= SKIN_DEGREES:
            return []
        return [
            LookWarning(
                "skin_protected",
                f"Portrait mode kept skin tones natural: the look would have "
                f"shifted skin hue by up to {held:.0f}°, and lookmatch held it "
                f"to about {drift:.0f}°. Skin will look a little less graded "
                "than the reference.",
            )
        ]
    if drift <= SKIN_DEGREES:
        return []
    return [
        LookWarning(
            "skin_drift",
            f"The look shifts skin-colored areas by up to {drift:.0f}° of hue, "
            "which can make faces look too orange, pink or green. If these "
            "photos have people, run again with --portrait to keep skin tones "
            "natural. (Sand, wood and red rock are skin-colored too; if there "
            "are no people, you can ignore this.)",
        )
    ]


def _references(look: Look) -> list[LookWarning]:
    refs = [p for p in look.photos if p.role == "reference"]
    small = [
        p
        for p in refs
        if p.width is not None
        and p.height is not None
        and min(p.width, p.height) < MIN_SHORT_SIDE
    ]
    compressed = [
        p
        for p in refs
        if p.jpeg_quality is not None and p.jpeg_quality < MIN_JPEG_QUALITY
    ]
    out = []
    if small:
        out.append(
            LookWarning(
                "reference_small",
                f"Some reference photos are small (under {MIN_SHORT_SIDE} pixels "
                f"on the short side): {_names(small)}. Small copies, such as "
                "thumbnails or screenshots from social media, are often "
                "resized and recompressed, which can change their colors. Use "
                "the largest version you can find.",
            )
        )
    if compressed:
        out.append(
            LookWarning(
                "reference_compressed",
                f"Some reference photos are heavily compressed JPEGs: "
                f"{_names(compressed)}. Strong compression smears colors into "
                "blocks and bands, which lookmatch may learn as part of the "
                "look. Use a higher quality copy if you can.",
            )
        )
    return out


def _inputs(look: Look) -> list[LookWarning]:
    mine = [p for p in look.photos if p.role == "input"]
    raw = [p for p in mine if p.source == "raw"]
    out = []
    if len(mine) < MIN_INPUTS:
        out.append(
            LookWarning(
                "few_inputs",
                f"Only {len(mine)} of your photos were used. lookmatch learns "
                "your camera's typical colors from them, so with fewer than "
                f"{MIN_INPUTS} the look may not suit photos you take later. Add "
                "more photos of different scenes and light.",
            )
        )
    if raw and len(raw) < len(mine):
        out.append(
            LookWarning(
                "mixed_inputs",
                f"Your photos mix camera RAW files ({len(raw)}) and exported "
                f"photos ({len(mine) - len(raw)}). They are rendered differently, "
                "so the look learns a blend of both. Use only exports from your "
                "editor (recommended) or only RAW files.",
            )
        )
    elif raw:
        out.append(
            LookWarning(
                "raw_inputs",
                "Your photos were RAW files, which lookmatch decoded itself. "
                "Your editing app renders RAW files a little differently, so "
                "the look may come out slightly different there. For the most "
                "accurate result, export your photos from your editor unedited "
                "(JPEG or 16-bit TIFF, same profile you edit with) and use those.",
            )
        )
    return out


def check(look: Look) -> list[LookWarning]:
    """Return every warning for a fitted look, most important first."""
    return [*_scenes(look), *_skin(look), *_references(look), *_inputs(look)]
