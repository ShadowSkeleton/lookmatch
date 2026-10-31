"""Measure how alike the reference scenes and your scenes are.

The full fit (whole tone curve, average tint, transport) is precise when the
references show the same kind of scenes as your photos, and harmful when
they don't: it copies the other scenes' content as if it were the look. The
pipeline blends it in by the scene match, from 0 (different scenes) to 1
(same scenes), the larger of two measurements:

1. Same photos. If a reference is a graded copy of one of your photos (you
   edited some of your own photos and want the rest to match), the two
   share their structure: where it is darker and lighter. A color grade
   changes the brightness of each area, but almost never their order, so
   the rank correlation of two small lightness thumbnails (Spearman 1904)
   stays near 1. On the maintainer's 45 photos, graded copies scored 0.994
   or more under every benchmark look, and two different photos at most
   0.895 (two frames of one burst). The match is the fraction of reference
   photos that are copies of one of your photos.
2. Similar scenes. After the safe part of the look is applied to your
   photos, the sliced Wasserstein distance d to the reference colors
   (OKLab) gives a match of exp(-(d / SCENE_SCALE)^2).
"""

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt
from PIL import Image
from scipy.stats import rankdata

from lookmatch import io

THUMB_SIZE = 48  # thumbnail side, pixels
SAME_PHOTO = 0.97  # rank correlation above which two photos are one scene
MAX_ASPECT_DIFFERENCE = 0.02  # a crop changes the aspect ratio: not a copy
SCENE_SCALE = 0.02  # OKLab distance at which the scene match is 1/e


def structure(srgb: npt.ArrayLike) -> npt.NDArray[np.float64]:
    """Return a photo's structure: ranked lightness of a small thumbnail.

    The ranks are centered and scaled, so the dot product of two structures
    divided by their length is their rank correlation.
    """
    image = np.asarray(srgb, dtype=np.float32)
    if image.ndim != 3 or image.shape[-1] != 3:
        raise ValueError(f"Expected an RGB image, got shape {image.shape}.")
    lightness = np.asarray(io.srgb_to_oklab(image)[..., 0], dtype=np.float32)
    thumb = Image.fromarray(lightness).resize(
        (THUMB_SIZE, THUMB_SIZE), Image.Resampling.BOX
    )
    ranks = rankdata(np.asarray(thumb, dtype=np.float64).ravel())
    spread = ranks.std()
    if spread == 0:  # a flat image has no structure to compare
        return np.zeros(ranks.size)
    return np.asarray((ranks - ranks.mean()) / spread, dtype=np.float64)


def aspect(srgb: npt.ArrayLike) -> float:
    """Return a photo's width / height."""
    shape = np.shape(srgb)
    return float(shape[1]) / float(shape[0])


def copied_fraction(
    references: Sequence[tuple[npt.NDArray[np.float64], float]],
    inputs: Sequence[tuple[npt.NDArray[np.float64], float]],
) -> float:
    """Return the fraction of references that are graded copies of an input.

    Each photo is given as (structure, aspect ratio).
    """
    if not references or not inputs:
        return 0.0
    copies = 0
    for ref, ref_aspect in references:
        for mine, my_aspect in inputs:
            if abs(ref_aspect / my_aspect - 1.0) > MAX_ASPECT_DIFFERENCE:
                continue
            if float(ref @ mine) / ref.size >= SAME_PHOTO:
                copies += 1
                break
    return copies / len(references)


def distance_match(distance: float, scale: float = SCENE_SCALE) -> float:
    """Return the scene match from a color distance: exp(-(d / scale)^2)."""
    return float(np.exp(-((distance / scale) ** 2)))


def scene_match(copied: float, distance: float) -> float:
    """Combine both measurements: the larger one wins."""
    return max(float(copied), distance_match(distance))
