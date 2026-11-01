import re
import xml.dom.minidom
from pathlib import Path

import numpy as np
import pytest

from lookmatch import io, tone
from lookmatch.export import lr_preset
from lookmatch.look import Look
from lookmatch.toning import SplitToning

FIXTURE = Path(__file__).parent / "fixtures" / "lr_preset_reference.xmp"
LEVELS = np.arange(256, dtype=np.float64)


def _curve(points: list[tuple[int, int]]) -> np.ndarray:
    xs, ys = zip(*points, strict=True)
    return np.interp(LEVELS, xs, ys)


def _fields(text: str) -> set[str]:
    return set(re.findall(r"crs:(\w+)", text))


def test_identity_look_gives_straight_curves() -> None:
    curves = lr_preset.preset_curves(Look(name="none"))
    for points in curves.values():
        np.testing.assert_allclose(_curve(points), LEVELS, atol=1.0)


def test_every_field_comes_from_a_real_lightroom_preset() -> None:
    look = Look(name="t", split_toning=SplitToning((0.02, 0.0), (0, 0), (0, 0.02)))
    ours = _fields(lr_preset.format_preset(look))
    assert ours <= _fields(FIXTURE.read_text(encoding="utf-8"))
    assert {"ToneCurvePV2012", "ToneCurvePV2012Red", "ProcessVersion"} <= ours


def test_preset_is_valid_xml_with_any_name(tmp_path: Path) -> None:
    name = '雪天 "Snow" & <film>'
    path = tmp_path / "look.xmp"
    lr_preset.write_preset(path, Look(name=name))
    dom = xml.dom.minidom.parse(str(path))
    names = dom.getElementsByTagName("crs:Name")[0]
    assert names.getElementsByTagName("rdf:li")[0].firstChild.data == name


def test_master_curve_matches_the_tone_curve_on_grays() -> None:
    curve = np.clip(
        0.03 + 0.95 * tone.GRID + 0.05 * np.sin(2 * np.pi * tone.GRID), 0, 1
    )
    look = Look(name="t", tone_curve=list(np.maximum.accumulate(curve)))
    master = _curve(lr_preset.preset_curves(look)["master"])
    gray = np.stack([LEVELS / 255.0] * 3, axis=-1)
    lightness = tone.apply_tone_curve(io.srgb_to_oklab(gray)[:, 0], look.tone_curve)
    lab = np.stack([lightness, 0 * lightness, 0 * lightness], axis=-1)
    target = np.clip(io.oklab_to_srgb(lab)[:, 0], 0, 1) * 255
    error = np.abs(master - target)
    assert error[8:].max() < 1.5  # the deepest blacks rise too steeply for curves


def test_warm_highlights_and_cool_shadows_show_in_channel_curves() -> None:
    look = Look(
        name="t",
        split_toning=SplitToning((-0.02, -0.03), (0.0, 0.0), (0.01, 0.03)),
    )
    curves = lr_preset.preset_curves(look)
    red, green, blue = (_curve(curves[c]) for c in ("red", "green", "blue"))
    assert red[220] > green[220] > blue[220]  # warm highlights
    assert blue[40] > red[40]  # cool shadows
    assert lr_preset.format_preset(look) == lr_preset.format_preset(look)


def test_curve_points_follow_the_target() -> None:
    target = 255 * (LEVELS / 255) ** 0.8
    points = lr_preset.curve_points(target)
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    assert xs[0] == 0 and xs[-1] == 255
    assert all(b - a >= lr_preset.MIN_GAP for a, b in zip(xs, xs[1:], strict=False))
    assert ys == sorted(ys)
    assert len(points) <= lr_preset.MAX_POINTS
    assert np.abs(_curve(points) - target)[8:].max() < 1.5
    with pytest.raises(ValueError, match="256 levels"):
        lr_preset.curve_points(np.zeros(10))
