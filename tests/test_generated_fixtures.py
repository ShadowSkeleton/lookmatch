"""The committed test LUT and test chart must match their generator exactly."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import numpy as np
from PIL import Image

from lookmatch import io
from lookmatch.apply import apply_lut
from lookmatch.export.cube import read_cube

FIXTURES = Path(__file__).parent / "fixtures"


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "make_fixtures", FIXTURES / "make_fixtures.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gen = _generator()


# --- Committed files are reproducible ------------------------------------------


def test_committed_test_look_matches_generator() -> None:
    committed = read_cube(FIXTURES / "test_look_33.cube")
    fresh = gen.make_test_look()
    assert committed.size == 33
    np.testing.assert_allclose(committed.table, fresh.table, atol=5e-7)


def test_committed_chart_matches_generator() -> None:
    pixels, layout = gen.make_chart()
    committed = np.asarray(Image.open(FIXTURES / "test_chart.png"))
    np.testing.assert_array_equal(committed, pixels)
    assert json.loads((FIXTURES / "test_chart.json").read_text()) == layout


# --- The test look does what its name says ----------------------------------


def _gray(v: float) -> np.ndarray:
    return np.array([[v, v, v]])


def test_shadows_warm_highlights_cool() -> None:
    look = gen.make_test_look()
    shadow = apply_lut(_gray(0.2), look)[0]
    highlight = apply_lut(_gray(0.85), look)[0]
    assert shadow[0] > shadow[2] + 0.02  # red above blue: warm
    assert highlight[2] > highlight[0] + 0.02  # blue above red: cool


def test_gray_ramp_lightness_is_monotonic() -> None:
    look = gen.make_test_look()
    ramp = np.linspace(0, 1, 256)
    out = apply_lut(np.repeat(ramp[:, None], 3, axis=1), look)
    lightness = io.srgb_to_oklab(out)[:, 0]
    assert np.all(np.diff(lightness) > 0)


def test_test_look_stays_in_gamut() -> None:
    table = gen.make_test_look().table
    assert table.min() >= 0.0 and table.max() <= 1.0


# --- The chart has the patches the QA script relies on -------------------------


def test_chart_layout() -> None:
    pixels, layout = gen.make_chart()
    assert pixels.dtype == np.uint8 and pixels.shape[2] == 3
    names = [p["name"] for p in layout["patches"]]
    assert len(names) == len(set(names))
    assert sum(n.startswith("gray ") for n in names) == 33
    assert sum(p["group"] == "colorchecker" for p in layout["patches"]) == 24
    for patch in layout["patches"]:
        x, y, w, h = patch["x"], patch["y"], patch["w"], patch["h"]
        region = pixels[y : y + h, x : x + w].reshape(-1, 3)
        assert np.all(region == patch["rgb8"]), patch["name"]


def test_chart_known_values() -> None:
    _, layout = gen.make_chart()
    by_name = {p["name"]: p for p in layout["patches"]}
    assert by_name["gray 00"]["rgb8"] == [0, 0, 0]
    assert by_name["gray 32"]["rgb8"] == [255, 255, 255]
    # Published sRGB for the ColorChecker "dark skin" patch is about (115, 82, 68).
    dark_skin = np.array(by_name["dark skin"]["rgb8"])
    assert np.all(np.abs(dark_skin - [115, 82, 68]) <= 4)
