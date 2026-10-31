from typing import Any

import pytest

from lookmatch import checks
from lookmatch.look import Look, Photo


def _photo(
    name: str,
    role: str = "input",
    source: str = "rendered",
    size: tuple[int, int] = (6000, 4000),
    quality: int | None = 92,
) -> Photo:
    return Photo(
        file=name,
        sha256="0" * 64,
        role=role,
        source=source,
        illuminant=[1.0, 1.0, 1.0],
        median_luminance=0.18,
        reliable=True,
        white_balance=[1.0, 1.0, 1.0],
        exposure=1.0,
        width=size[0],
        height=size[1],
        jpeg_quality=quality,
    )


GOOD_METRICS = {
    "scene_match": 0.9,
    "skin_fraction": 0.1,
    "skin_hue_drift_p95": 2.0,
}


def _look(
    refs: list[Photo] | None = None,
    mine: list[Photo] | None = None,
    portrait: bool = False,
    **metrics: float,
) -> Look:
    refs = (
        refs
        if refs is not None
        else [_photo(f"r{i}.jpg", "reference") for i in range(3)]
    )
    mine = mine if mine is not None else [_photo(f"m{i}.jpg") for i in range(8)]
    settings: dict[str, Any] = {"portrait": portrait}
    return Look(
        name="t", settings=settings, photos=refs + mine, metrics=GOOD_METRICS | metrics
    )


def _codes(look: Look) -> list[str]:
    return [w.code for w in checks.check(look)]


def test_a_good_run_has_no_warnings() -> None:
    assert _codes(_look()) == []


def test_scenes_differ() -> None:
    warnings = checks.check(_look(scene_match=0.2))
    assert [w.code for w in warnings] == ["scenes_differ"]
    assert "20%" in warnings[0].message


@pytest.mark.parametrize("portrait", [False, True])
def test_skin_drift(portrait: bool) -> None:
    look = _look(
        portrait=portrait,
        skin_hue_drift_p95=12.0 if not portrait else 5.0,
        skin_hue_drift_p95_unprotected=12.0,
    )
    expected = "skin_protected" if portrait else "skin_drift"
    assert _codes(look) == [expected]
    message = checks.check(look)[0].message
    assert ("--portrait" in message) != portrait


def test_little_skin_is_not_judged() -> None:
    assert _codes(_look(skin_fraction=0.001, skin_hue_drift_p95=30.0)) == []


def test_reference_small_and_compressed() -> None:
    refs = [
        _photo("tiny.jpg", "reference", size=(640, 427)),
        _photo("blocky.jpg", "reference", quality=45),
        _photo("fine.png", "reference", quality=None),
    ]
    warnings = checks.check(_look(refs=refs))
    assert [w.code for w in warnings] == ["reference_small", "reference_compressed"]
    assert "tiny.jpg" in warnings[0].message and "blocky.jpg" in warnings[1].message


def test_few_inputs() -> None:
    assert _codes(_look(mine=[_photo("a.jpg"), _photo("b.jpg")])) == ["few_inputs"]


def test_raw_and_mixed_inputs() -> None:
    raw = [_photo(f"{i}.ARW", source="raw", quality=None) for i in range(6)]
    assert _codes(_look(mine=raw)) == ["raw_inputs"]
    assert _codes(_look(mine=raw + [_photo("x.jpg")])) == ["mixed_inputs"]


def test_old_files_without_sizes_are_fine() -> None:
    refs = [_photo("r.jpg", "reference")]
    refs[0].width = refs[0].height = refs[0].jpeg_quality = None
    assert _codes(_look(refs=refs)) == []


def test_messages_are_plain_and_list_few_names() -> None:
    refs = [_photo(f"r{i}.jpg", "reference", size=(300, 200)) for i in range(6)]
    message = checks.check(_look(refs=refs))[0].message
    assert "r0.jpg, r1.jpg, r2.jpg and 3 more" in message
    for w in checks.check(_look(scene_match=0.1, skin_hue_drift_p95=20.0)):
        assert "Wasserstein" not in w.message and "OKLab" not in w.message
