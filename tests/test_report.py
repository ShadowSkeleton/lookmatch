import re
from pathlib import Path

import numpy as np
from PIL import Image

from lookmatch import report
from lookmatch.export.cube import Cube, identity_table
from lookmatch.look import Look, LookWarning, Photo
from lookmatch.toning import SplitToning


def _photo(name: str, role: str) -> Photo:
    return Photo(
        file=name,
        sha256="0" * 64,
        role=role,
        source="rendered",
        illuminant=[1.0, 1.0, 1.0],
        median_luminance=0.18,
        reliable=True,
        white_balance=[1.0, 1.0, 1.0],
        exposure=1.0,
    )


def _look(**kwargs: object) -> Look:
    base: dict[str, object] = {
        "name": "Snow & <portrait>",
        "photos": [_photo("r.jpg", "reference"), _photo("m.jpg", "input")],
        "tone_curve": list(np.linspace(0.05, 1, 256)),
        "split_toning": SplitToning((-0.02, -0.03), (0.0, 0.0), (0.012, 0.03)),
        "metrics": {
            "scene_match": 0.9,
            "color_distance_before": 0.1,
            "color_distance_after": 0.04,
            "lightness_distance_before": 0.05,
            "lightness_distance_after": 0.01,
            "skin_fraction": 0.1,
            "skin_hue_drift_p95": 3.0,
            "ssim_mean": 0.98,
            "ssim_min": 0.95,
        },
        "settings": {"portrait": False, "lut_size": 33},
    }
    base.update(kwargs)
    return Look(**base)  # type: ignore[arg-type]


def _cube() -> Cube:
    return Cube(np.clip(identity_table(9) * 0.9 + 0.05, 0, 1))


def test_report_is_one_offline_file(tmp_path: Path) -> None:
    photo = tmp_path / "mine.png"
    Image.new("RGB", (300, 200), (120, 140, 160)).save(photo)
    previews = report.make_previews([photo], _cube(), max_side=100)
    look = _look(warnings=[LookWarning("few_inputs", "Only 1 of your photos.")])
    html = report.render_report(look, previews, ["look.json"])
    # No outside requests: no external scripts, styles, fonts or images.
    assert not re.search(r'(src|href)="(https?:)?//(?!github.com)', html)
    assert "<script" not in html
    assert html.count("data:image/jpeg;base64,") == 2  # before and after
    assert "Only 1 of your photos." in html and 'data-code="few_inputs"' in html
    assert "Snow &amp; &lt;portrait&gt;" in html  # names are escaped
    assert "No problems found" not in html
    assert 'name="viewport"' in html and "prefers-color-scheme: dark" in html
    path = report.write_report(tmp_path / "report.html", look, previews)
    assert path.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_no_warnings_and_no_previews() -> None:
    html = report.render_report(_look())
    assert "No problems found" in html
    assert "Your photos with the look" not in html


def test_previews_measure_ssim(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    pixels = (rng.random((120, 180, 3)) * 255).astype(np.uint8)
    Image.fromarray(pixels).save(tmp_path / "a.png")
    previews = report.make_previews([tmp_path / "a.png"], _cube(), max_side=90)
    assert previews[0].before.shape == (60, 90, 3)
    assert previews[0].after.dtype == np.uint8
    assert 0.5 < previews[0].ssim < 1.0
    metrics = report.preview_metrics(previews)
    assert metrics["ssim_min"] == metrics["ssim_mean"] == previews[0].ssim
    assert report.preview_metrics([]) == {}
    assert Image.open(tmp_path / "a.png").size == (180, 120)  # untouched


def test_plain_words_for_the_look() -> None:
    assert report.hue_name(55) == "orange"
    assert report.hue_name(200) == "teal"
    assert report.hue_name(359) == "pink"
    assert report.strength_name(0.001) == "none"
    assert report.strength_name(0.04) == "strong"
    rows = report.toning_rows(SplitToning((-0.03, -0.03), (0, 0), (0.0, 0.04)))
    assert [r["zone"] for r in rows] == ["Shadows", "Midtones", "Highlights"]
    assert rows[0]["words"].endswith("teal") or rows[0]["words"].endswith("blue")
    assert rows[2]["words"].endswith("yellow") or rows[2]["words"].endswith("orange")
    assert report.toning_rows(None)[1]["words"] == "No tint"
    assert report.scene_words(0.1, 1.0) == "Same photos"
    assert report.scene_words(0.1, 0.0) == "Different scenes"


def test_measurements_are_explained() -> None:
    rows = {r["name"]: r for r in report.measurement_rows(_look())}
    assert rows["Colors"]["value"] == "60% closer"
    assert rows["Brightness"]["value"] == "80% closer"
    assert "Skin tones" in rows and "Picture quality" in rows
    no_skin = _look(metrics={"skin_fraction": 0.0})
    names = [r["name"] for r in report.measurement_rows(no_skin)]
    assert "Skin tones" not in names and "Picture quality" not in names


def test_tone_curve_svg() -> None:
    svg = report.tone_curve_svg(list(np.linspace(0, 1, 256)))
    assert svg.startswith("<svg") and svg.count(",") == 256
    assert "aria-label" in svg
