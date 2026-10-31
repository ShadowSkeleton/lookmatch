"""Tests for bench/app_check.py, the task 1.5 app comparison script."""

import importlib.util
from pathlib import Path
from types import ModuleType

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = _load("app_check", ROOT / "bench" / "app_check.py")


def _save(tmp_path: Path, name: str, pixels: np.ndarray) -> Path:
    path = tmp_path / name
    Image.fromarray(pixels).save(path)
    return path


def test_lookmatch_result_passes(tmp_path: Path) -> None:
    expected = check.expected_pixels()
    report = check.compare(_save(tmp_path, "same.png", expected))
    assert report.verdict == "pass"
    assert report.max_diff <= 1


def test_small_differences_pass(tmp_path: Path) -> None:
    pixels = check.expected_pixels().astype(int)
    pixels[::2] += 1  # one level off on half the rows
    report = check.compare(
        _save(tmp_path, "close.png", np.clip(pixels, 0, 255).astype(np.uint8))
    )
    assert report.verdict == "pass"


def test_large_differences_fail(tmp_path: Path) -> None:
    pixels = check.expected_pixels().astype(int)
    pixels[..., 2] += 12  # a strong blue shift
    report = check.compare(
        _save(tmp_path, "off.png", np.clip(pixels, 0, 255).astype(np.uint8))
    )
    assert report.verdict == "fail"
    assert report.max_diff >= 10
    assert "different" in report.message


def test_lut_not_applied_is_detected(tmp_path: Path) -> None:
    original, _ = check.chart()
    report = check.compare(_save(tmp_path, "orig.png", original))
    assert report.verdict == "not applied"
    assert "wasn't applied" in report.message


def test_wrong_size_is_detected(tmp_path: Path) -> None:
    small = Image.fromarray(check.expected_pixels()).resize((640, 510))
    path = tmp_path / "small.png"
    small.save(path)
    report = check.compare(path)
    assert report.verdict == "wrong size"
    assert "1280 x 1020" in report.message


def test_format_report_is_readable(tmp_path: Path) -> None:
    report = check.compare(_save(tmp_path, "same.png", check.expected_pixels()))
    text = check.format_report("Photoshop", report)
    assert "Photoshop" in text and "PASS" in text
