import sys
from pathlib import Path

import numpy as np
import pytest

from lookmatch import scenes
from lookmatch.apply import apply_lut

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
import make_fixtures  # noqa: E402

LOOK = make_fixtures.make_test_look()


def _photo(seed: int, h: int = 120, w: int = 180) -> np.ndarray:
    """Smooth random structure: a few blurred blobs."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w] / max(h, w)
    image = np.zeros((h, w, 3))
    for _ in range(8):
        cy, cx, r = rng.random(3) * [1, 1.5, 0.3] + [0, 0, 0.05]
        blob = np.exp(-((y - cy) ** 2 + (x - cx) ** 2) / r**2)
        image += blob[..., None] * rng.random(3)
    return np.clip(image / image.max(), 0, 1)


def _shape(image: np.ndarray) -> tuple[np.ndarray, float]:
    return scenes.structure(image), scenes.aspect(image)


def test_graded_copy_has_the_same_structure() -> None:
    photo = _photo(1)
    graded = apply_lut(photo, LOOK)
    s1, s2 = scenes.structure(photo), scenes.structure(graded)
    assert float(s1 @ s2) / s1.size > 0.99
    other = scenes.structure(_photo(2))
    assert float(s1 @ other) / s1.size < scenes.SAME_PHOTO


def test_structure_ignores_size() -> None:
    photo = _photo(3, 120, 180)
    small = _photo(3, 60, 90)
    s1, s2 = scenes.structure(photo), scenes.structure(small)
    assert float(s1 @ s2) / s1.size > 0.98


def test_copied_fraction() -> None:
    mine = [_shape(_photo(i)) for i in range(4)]
    refs = [_shape(apply_lut(_photo(i), LOOK)) for i in (0, 1)] + [_shape(_photo(10))]
    assert scenes.copied_fraction(refs, mine) == pytest.approx(2 / 3)
    assert scenes.copied_fraction([], mine) == 0.0
    # A crop changes the aspect ratio, so it doesn't count as a copy.
    cropped = _photo(0)[:, :120]
    assert scenes.copied_fraction([_shape(cropped)], mine) == 0.0


def test_flat_image_has_no_structure() -> None:
    flat = np.full((20, 30, 3), 0.5)
    assert not np.any(scenes.structure(flat))


def test_scene_match() -> None:
    assert scenes.distance_match(0.0) == 1.0
    assert scenes.distance_match(scenes.SCENE_SCALE) == pytest.approx(np.exp(-1))
    assert scenes.distance_match(0.1) < 1e-6
    assert scenes.scene_match(1.0, 0.1) == 1.0
    assert scenes.scene_match(0.0, 0.0) == 1.0
    assert scenes.scene_match(0.25, 0.1) == 0.25


def test_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="RGB"):
        scenes.structure(np.zeros((10, 10)))


def test_effective_count() -> None:
    from lookmatch.scenes import effective_count

    assert effective_count(5, 0.0, 1.0) == pytest.approx(1.0)  # one shoot
    assert effective_count(5, 1.0, 1.0) == pytest.approx(5.0)  # as varied as yours
    assert effective_count(5, 2.0, 1.0) == pytest.approx(5.0)
    assert 1.0 < effective_count(5, 0.5, 1.0) < 5.0
    assert effective_count(1, 0.0, 1.0) == pytest.approx(1.0)


def test_shrink_weight() -> None:
    from lookmatch.scenes import shrink_weight

    signal, spread = np.array([0.01, 0.01]), np.array([0.001, 0.001])
    alone = shrink_weight(signal, spread, 10, None, caution=2.0)
    np.testing.assert_allclose(alone, 0.01 / (0.01 + 2.0 * 0.0001))
    # The same references, but your photos show scenes scatter a lot more:
    # agreeing references are one shoot, so the change is shrunk hard.
    shoot = shrink_weight(signal, spread, 10, np.array([0.02, 0.02]), caution=2.0)
    assert np.all(shoot < 0.3)
    assert shrink_weight(np.zeros(1), np.zeros(1), 3, np.zeros(1), 2.0)[0] == 0.0
