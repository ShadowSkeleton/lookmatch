import sys
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from lookmatch import io
from lookmatch.apply import apply_lut
from lookmatch.export.cube import Cube
from lookmatch.look import load_look, save_look
from lookmatch.pipeline import (
    DEFAULT_TRANSPORT_STRENGTH,
    collect_photos,
    fit,
)

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
import make_fixtures  # noqa: E402

LOOK = make_fixtures.make_test_look()


def _scene(seed: int, w: int = 360, h: int = 240) -> np.ndarray:
    """A small landscape-like image: sky gradient, ground, a few objects."""
    rng = np.random.default_rng(seed)
    y = np.linspace(0, 1, h)[:, None, None]
    x = np.linspace(0, 1, w)[None, :, None]
    sky = np.array([0.45, 0.62, 0.85]) * (1.1 - 0.4 * y) + 0.05 * x
    ground = np.array([0.55, 0.38, 0.25]) * (0.6 + 0.4 * y) + 0.03 * x
    horizon = rng.uniform(0.35, 0.6)
    img = np.where(y < horizon, sky, ground)
    for _ in range(6):  # rocks, bushes, a white object
        color = rng.choice([[0.25, 0.4, 0.2], [0.7, 0.45, 0.3], [0.9, 0.9, 0.88]])
        cx, cy, r = rng.uniform(0, w), rng.uniform(h * horizon, h), rng.uniform(10, 40)
        yy, xx = np.mgrid[0:h, 0:w]
        img = np.where(((xx - cx) ** 2 + (yy - cy) ** 2 < r**2)[..., None], color, img)
    img = img + rng.normal(0, 0.01, img.shape)
    return np.clip(img, 0, 1)


def _save(path: Path, srgb: np.ndarray) -> Path:
    Image.fromarray(np.round(srgb * 255).astype(np.uint8)).save(path)
    return path


@pytest.fixture
def folders(tmp_path: Path) -> tuple[Path, Path]:
    """Reference photos with the test look, and different input photos."""
    refs, inputs = tmp_path / "refs", tmp_path / "mine"
    refs.mkdir()
    inputs.mkdir()
    for i in range(3):
        _save(refs / f"ref_{i}.png", apply_lut(_scene(100 + i), LOOK))
    for i in range(5):
        _save(inputs / f"img_{i}.jpg", _scene(200 + i))
    (inputs / ".DS_Store").write_bytes(b"\0")  # must be ignored
    (inputs / "notes.txt").write_text("not a photo")
    return refs, inputs


def _error(cube: Cube, truth: Cube) -> tuple[float, float]:
    """Mean error on a held-out photo, and the error of not applying any look."""
    held_out = _scene(999)  # a photo used by neither side
    want = apply_lut(held_out, truth)
    error = np.abs(apply_lut(held_out, cube) - want) * 255
    return float(error.mean()), float(np.abs(held_out - want).mean() * 255)


def test_fit_learns_the_look_from_other_scenes(folders: tuple[Path, Path]) -> None:
    refs, inputs = folders
    result = fit(refs, inputs, name="test look")
    error, no_look = _error(result.cube, LOOK)
    assert error < 0.6 * no_look, (error, no_look)


def test_fit_learns_the_look_closely_from_the_same_scenes(tmp_path: Path) -> None:
    refs, inputs = tmp_path / "refs", tmp_path / "mine"
    refs.mkdir()
    inputs.mkdir()
    for i in range(5):
        _save(inputs / f"img_{i}.png", _scene(200 + i))
        _save(refs / f"ref_{i}.png", apply_lut(_scene(200 + i), LOOK))
    result = fit(refs, inputs)
    error, no_look = _error(result.cube, LOOK)
    assert error < 0.2 * no_look, (error, no_look)
    assert result.look.metrics["references_copied_from_inputs"] == 1.0
    assert result.look.metrics["scene_match"] == 1.0


def test_other_scenes_without_a_look_change_little(tmp_path: Path) -> None:
    # References with no look at all, showing other scenes: the LUT should
    # stay close to no change instead of copying the other scenes' colors.
    refs, inputs = tmp_path / "refs", tmp_path / "mine"
    refs.mkdir()
    inputs.mkdir()
    for i in range(3):
        _save(refs / f"ref_{i}.png", _scene(100 + i))
    for i in range(5):
        _save(inputs / f"img_{i}.png", _scene(200 + i))
    result = fit(refs, inputs)
    held_out = _scene(999)
    change = np.abs(apply_lut(held_out, result.cube) - held_out).mean() * 255
    assert change < 3.0, change


def test_fit_is_fast(folders: tuple[Path, Path]) -> None:
    refs, inputs = folders
    start = time.perf_counter()
    fit(refs, inputs)
    assert time.perf_counter() - start < 10.0


def test_fit_is_reproducible(folders: tuple[Path, Path], tmp_path: Path) -> None:
    refs, inputs = folders
    a, b = fit(refs, inputs, name="x"), fit(refs, inputs, name="x")
    np.testing.assert_array_equal(a.cube.table, b.cube.table)
    save_look(a.look, tmp_path / "a.json")
    save_look(b.look, tmp_path / "b.json")
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()


def test_look_records_everything(folders: tuple[Path, Path], tmp_path: Path) -> None:
    refs, inputs = folders
    result = fit(refs, inputs, name="雪天人像")
    look = result.look
    assert look.name == "雪天人像"
    assert [p.role for p in look.photos] == ["reference"] * 3 + ["input"] * 5
    assert {p.source for p in look.photos} == {"rendered"}
    assert [p.file for p in look.photos][:2] == ["ref_0.png", "ref_1.png"]
    assert look.settings["transport_strength"] == DEFAULT_TRANSPORT_STRENGTH
    assert look.settings["portrait"] is False
    assert look.settings["lut_size"] == 33
    assert look.tone_curve is not None and len(look.tone_curve) == 256
    assert look.split_toning is not None
    for key in ("lut_total_variation", "lut_coverage", "skin_hue_drift_mean"):
        assert key in look.metrics
    m = look.metrics
    assert m["color_distance_after"] < m["color_distance_before"]
    assert m["lightness_distance_after"] < m["lightness_distance_before"]
    save_look(look, tmp_path / "look.json")
    assert load_look(tmp_path / "look.json") == look
    assert result.cube.title == "雪天人像"


def test_single_reference_file_and_lists(folders: tuple[Path, Path]) -> None:
    refs, inputs = folders
    result = fit(refs / "ref_0.png", sorted(inputs.glob("*.jpg"))[:3])
    assert sum(p.role == "reference" for p in result.look.photos) == 1
    assert sum(p.role == "input" for p in result.look.photos) == 3


def test_portrait_mode_runs_and_is_recorded(folders: tuple[Path, Path]) -> None:
    refs, inputs = folders
    result = fit(refs, inputs, portrait=True)
    assert result.look.settings["portrait"] is True


def test_collect_photos_sorts_and_filters(folders: tuple[Path, Path]) -> None:
    _, inputs = folders
    names = [p.name for p in collect_photos(inputs)]
    assert names == [f"img_{i}.jpg" for i in range(5)]


def test_clear_errors(tmp_path: Path, folders: tuple[Path, Path]) -> None:
    refs, _ = folders
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="no photos"):
        fit(refs, empty)
    with pytest.raises(FileNotFoundError, match="Can't find"):
        fit(tmp_path / "missing", refs)
    with pytest.raises(ValueError, match="strength"):
        fit(refs, refs, transport_strength=2.0)


def test_inputs_are_not_modified(folders: tuple[Path, Path]) -> None:
    refs, inputs = folders
    before = {p: p.read_bytes() for p in inputs.iterdir()}
    fit(refs, inputs)
    assert {p: p.read_bytes() for p in inputs.iterdir()} == before


def test_raw_inputs_are_marked(
    folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    refs, inputs = folders
    raw = inputs / "shot.ARW"
    raw.write_bytes(b"\0")
    fake = io.load_image(inputs / "img_0.jpg")
    real_load = io.load_image
    monkeypatch.setattr(
        "lookmatch.pipeline.io.load_image",
        lambda p: fake if Path(p).suffix == ".ARW" else real_load(p),
    )
    result = fit(refs, inputs)
    sources = {p.file: p.source for p in result.look.photos}
    assert sources["shot.ARW"] == "raw"
    assert sources["img_0.jpg"] == "rendered"
    codes = [w.code for w in result.look.warnings]
    assert "mixed_inputs" in codes
    # The synthetic references are 360 x 240: smaller than a real photo.
    assert "reference_small" in codes
