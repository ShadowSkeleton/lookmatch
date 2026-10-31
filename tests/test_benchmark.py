"""Tests for bench/benchmark.py, on tiny synthetic photos."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest
from PIL import Image

from lookmatch.apply import apply_lut
from lookmatch.metrics import delta_e_2000

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bench"))


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "bench" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bench = _load("benchmark")


@pytest.fixture(scope="module")
def photo_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("photos")
    for i in range(5):
        rng = np.random.default_rng(i)
        base = rng.uniform(0.2, 0.7, 3)
        y = np.linspace(0, 1, 60)[:, None, None]
        img = np.clip(base * (0.4 + y) + rng.normal(0, 0.05, (60, 90, 3)), 0, 1)
        Image.fromarray(np.round(img * 255).astype(np.uint8)).save(folder / f"p{i}.png")
    return folder


@pytest.fixture(scope="module")
def result(photo_dir: Path, tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    looks = {n: bench.builtin_looks()[n] for n in ("warm_cool_test", "bleach_bypass")}
    photos = bench.load_photos(photo_dir, max_side=90)
    work = tmp_path_factory.mktemp("work")
    return bench.run(photos, looks, max_folds=1, workdir=work), photos, looks


def test_every_method_scored(result) -> None:  # type: ignore[no-untyped-def]
    scores, photos, looks = result
    methods = {s.method for s in scores}
    assert methods == set(bench.METHODS)
    conditions = {s.condition for s in scores}
    assert conditions == {"different scenes", "same scenes"}
    assert all(np.isfinite(s.mean_de) and s.p95_de >= s.mean_de for s in scores)


def test_no_change_score_is_the_looks_own_difference(result) -> None:  # type: ignore[no-untyped-def]
    scores, photos, looks = result
    s = next(x for x in scores if x.method == "no change")
    pixels = bench.score_pixels(dict(photos)[s.photo])
    truth = apply_lut(pixels, looks[s.look])
    assert s.mean_de == pytest.approx(float(delta_e_2000(pixels, truth).mean()))


def test_scoring_sample_matches_whole_photo(photo_dir: Path) -> None:
    look = bench.builtin_looks()["teal_orange"]
    _, image = bench.load_photos(photo_dir, max_side=400)[0]
    whole = float(delta_e_2000(image, apply_lut(image, look)).mean())
    pixels = bench.score_pixels(image)
    sampled = float(delta_e_2000(pixels, apply_lut(pixels, look)).mean())
    assert sampled == pytest.approx(whole, rel=0.02)


def test_folds_never_share_photos() -> None:
    for ref, inputs in bench.folds(7, max_folds=3):
        assert set(ref).isdisjoint(inputs)
        assert len(ref) + len(inputs) == 7


def test_summary_and_report(result, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    scores, photos, looks = result
    rows = bench.summarize(scores)
    assert {(r["condition"], r["method"]) for r in rows} == {
        (c, m) for c in ("different scenes", "same scenes") for m in bench.METHODS
    }
    no_change = [r for r in rows if r["method"] == "no change"]
    assert all(r["worse_than_no_change"] == 0.0 for r in no_change)
    md, js = tmp_path / "RESULTS.md", tmp_path / "results.json"
    bench.write_report(scores, {"photos": len(photos)}, md, js)
    text = md.read_text()
    assert "| lookmatch |" in text and "ΔE 2000" in text
    assert len(json.loads(js.read_text())["scores"]) == len(scores)


def test_is_deterministic(photo_dir: Path, tmp_path: Path) -> None:
    looks = {"warm_cool_test": bench.builtin_looks()["warm_cool_test"]}
    photos = bench.load_photos(photo_dir, max_side=60)
    a = bench.run(
        photos, looks, max_folds=1, workdir=tmp_path / "a", conditions=("same scenes",)
    )
    b = bench.run(
        photos, looks, max_folds=1, workdir=tmp_path / "b", conditions=("same scenes",)
    )
    assert a == b


def test_too_few_photos(tmp_path: Path) -> None:
    Image.new("RGB", (10, 10)).save(tmp_path / "only.png")
    with pytest.raises(ValueError, match="at least"):
        bench.run(bench.load_photos(tmp_path), bench.builtin_looks(), workdir=tmp_path)
