import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

import lookmatch
from lookmatch.look import (
    SCHEMA_VERSION,
    Look,
    LookWarning,
    Photo,
    load_look,
    save_look,
)
from lookmatch.neutralize import Correction, Estimate
from lookmatch.toning import SplitToning


def _photo(tmp_path: Path, name: str = "DSC0001.jpg", role: str = "input") -> Photo:
    path = tmp_path / name
    path.write_bytes(b"pretend photo bytes " + name.encode())
    est = Estimate(np.array([1.1, 0.98, 0.9]), 0.18, reliable=True)
    cor = Correction(np.array([0.95, 1.01, 1.08]), 1.25)
    return Photo.from_estimate(
        path, role=role, source="rendered", estimate=est, correction=cor
    )


def _look(tmp_path: Path) -> Look:
    curve = list(np.linspace(0, 1, 256) ** 0.9)
    return Look(
        name="Snow portrait",
        settings={"lut_size": 33, "transport_strength": 0.5, "rendering": "rendered"},
        photos=[_photo(tmp_path, "ref.jpg", "reference"), _photo(tmp_path)],
        tone_curve=curve,
        split_toning=SplitToning((-0.02, -0.03), (0.0, 0.001), (0.012, 0.03)),
        metrics={"sliced_wasserstein": 0.0123},
        warnings=[LookWarning("few_inputs", "Only 1 input photo.")],
    )


def test_round_trip(tmp_path: Path) -> None:
    look = _look(tmp_path)
    path = tmp_path / "look.json"
    save_look(look, path)
    assert load_look(path) == look


def test_floats_are_exact(tmp_path: Path) -> None:
    look = _look(tmp_path)
    look.metrics["tricky"] = 0.1 + 0.2
    path = tmp_path / "look.json"
    save_look(look, path)
    assert load_look(path).metrics["tricky"] == 0.1 + 0.2


def test_file_is_identical_every_time(tmp_path: Path) -> None:
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    save_look(_look(tmp_path), a)
    save_look(_look(tmp_path), b)
    assert a.read_bytes() == b.read_bytes()


def test_file_records_version_and_seed(tmp_path: Path) -> None:
    path = tmp_path / "look.json"
    save_look(_look(tmp_path), path)
    data = json.loads(path.read_text())
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["lookmatch_version"] == lookmatch.__version__
    assert data["seed"] == 0
    assert list(data)[:4] == ["schema_version", "lookmatch_version", "seed", "name"]


def test_photo_keeps_only_file_name_and_hash(tmp_path: Path) -> None:
    photo = _photo(tmp_path, "secret_folder_photo.jpg")
    expected = hashlib.sha256((tmp_path / "secret_folder_photo.jpg").read_bytes())
    assert photo.file == "secret_folder_photo.jpg"
    assert str(tmp_path) not in photo.file
    assert photo.sha256 == expected.hexdigest()
    assert photo.white_balance == [0.95, 1.01, 1.08]
    assert photo.exposure == 1.25


def test_chinese_names_survive(tmp_path: Path) -> None:
    look = _look(tmp_path)
    look.name = "雪天人像（日系）"
    path = tmp_path / "look.json"
    save_look(look, path)
    assert load_look(path).name == "雪天人像（日系）"
    assert "雪天人像" in path.read_text(encoding="utf-8")


# --- Validation ----------------------------------------------------------------


def test_rejects_bad_tone_curve(tmp_path: Path) -> None:
    look = _look(tmp_path)
    with pytest.raises(ValueError, match="256"):
        save_look(Look(name="x", tone_curve=[0.0, 1.0]), tmp_path / "a.json")
    bumpy = list(look.tone_curve or [])
    bumpy[100] = bumpy[99] - 0.01
    with pytest.raises(ValueError, match="never go down"):
        save_look(Look(name="x", tone_curve=bumpy), tmp_path / "b.json")


def test_rejects_nan(tmp_path: Path) -> None:
    look = _look(tmp_path)
    look.metrics["broken"] = float("nan")
    with pytest.raises(ValueError, match="NaN"):
        save_look(look, tmp_path / "look.json")


def test_rejects_bad_role_and_source(tmp_path: Path) -> None:
    photo = _photo(tmp_path)
    with pytest.raises(ValueError, match="role"):
        Photo(**{**photo.__dict__, "role": "other"})
    with pytest.raises(ValueError, match="source"):
        Photo(**{**photo.__dict__, "source": "film"})


def _write(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "look.json"
    path.write_text(json.dumps(data))
    return path


def test_newer_file_explains(tmp_path: Path) -> None:
    path = tmp_path / "look.json"
    save_look(_look(tmp_path), path)
    data = json.loads(path.read_text())
    data["schema_version"] = SCHEMA_VERSION + 1
    with pytest.raises(ValueError, match="newer version of lookmatch"):
        load_look(_write(tmp_path, data))


def test_unknown_field_explains(tmp_path: Path) -> None:
    path = tmp_path / "look.json"
    save_look(_look(tmp_path), path)
    data = json.loads(path.read_text())
    data["mystery"] = 1
    with pytest.raises(ValueError, match="mystery"):
        load_look(_write(tmp_path, data))


def test_damaged_file_explains(tmp_path: Path) -> None:
    path = tmp_path / "look.json"
    path.write_text("{ not json")
    with pytest.raises(ValueError, match="isn't a valid look.json"):
        load_look(path)
    with pytest.raises(ValueError, match="isn't a valid look.json"):
        load_look(_write(tmp_path, [1, 2, 3]))


def test_version_1_file_still_loads(tmp_path: Path) -> None:
    path = tmp_path / "look.json"
    save_look(_look(tmp_path), path)
    data = json.loads(path.read_text())
    data["schema_version"] = 1
    del data["split_toning"]
    look = load_look(_write(tmp_path, data))
    assert look.split_toning is None
    assert look.schema_version == SCHEMA_VERSION  # upgraded when saved again


def test_split_toning_is_saved_as_named_zones(tmp_path: Path) -> None:
    path = tmp_path / "look.json"
    save_look(_look(tmp_path), path)
    toning = json.loads(path.read_text())["split_toning"]
    assert toning == {
        "shadows": [-0.02, -0.03],
        "midtones": [0.0, 0.001],
        "highlights": [0.012, 0.03],
    }


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Can't find"):
        load_look(tmp_path / "nope.json")


def test_version_2_file_still_loads(tmp_path: Path) -> None:
    path = tmp_path / "look.json"
    save_look(_look(tmp_path), path)
    data = json.loads(path.read_text())
    data["schema_version"] = 2
    data["warnings"] = ["Only 1 input photo."]  # plain text in format 2
    for photo in data["photos"]:
        for key in ("width", "height", "jpeg_quality"):
            del photo[key]
    look = load_look(_write(tmp_path, data))
    assert look.warnings == [LookWarning("note", "Only 1 input photo.")]
    assert look.photos[0].width is None


def test_photo_records_size_and_jpeg_quality(tmp_path: Path) -> None:
    from PIL import Image

    path = tmp_path / "small.jpg"
    Image.new("RGB", (64, 48), (120, 130, 140)).save(path, quality=60)
    est = Estimate(np.ones(3), 0.18, True)
    cor = Correction(np.ones(3), 1.0)
    photo = Photo.from_estimate(path, "reference", "rendered", est, cor, (64, 48))
    assert (photo.width, photo.height) == (64, 48)
    assert photo.jpeg_quality == 60
