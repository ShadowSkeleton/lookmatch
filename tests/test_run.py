import sys
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from lookmatch.cli import app
from lookmatch.export.cube import read_cube
from lookmatch.look import load_look
from lookmatch.run import file_stem, run

sys.path.insert(0, str(Path(__file__).parent))
from test_pipeline import LOOK, _save, _scene  # noqa: E402

from lookmatch.apply import apply_lut  # noqa: E402

runner = CliRunner()


@pytest.fixture
def folders(tmp_path: Path) -> tuple[Path, Path]:
    refs, mine = tmp_path / "refs", tmp_path / "mine"
    refs.mkdir()
    mine.mkdir()
    for i in range(2):
        _save(refs / f"ref_{i}.png", apply_lut(_scene(100 + i), LOOK))
    for i in range(3):
        _save(mine / f"img_{i}.jpg", _scene(200 + i))
    _save(mine / "img_0.png", _scene(300))  # same name, other format
    return refs, mine


def _snapshot(folder: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in folder.iterdir()}


def test_run_writes_every_file(tmp_path: Path, folders: tuple[Path, Path]) -> None:
    refs, mine = folders
    before = _snapshot(refs) | _snapshot(mine)
    result = run(refs, mine, name="雪天: test/look", out=tmp_path / "looks")
    folder = tmp_path / "looks" / "雪天 test look"
    assert result.folder == folder
    for name in [
        "雪天 test look_33.cube",
        "雪天 test look_hald.png",
        "雪天 test look_preset.xmp",
        "LIGHTROOM_PROFILE.md",
        "look.json",
        "report.html",
    ]:
        assert (folder / name).is_file(), name
    previews = sorted(p.name for p in (folder / "previews").iterdir())
    assert previews == ["img_0_jpg.jpg", "img_0_png.jpg", "img_1.jpg", "img_2.jpg"]
    look = load_look(folder / "look.json")
    assert look.name == "雪天: test/look"
    assert 0 < look.metrics["ssim_min"] <= look.metrics["ssim_mean"] <= 1
    assert read_cube(folder / "雪天 test look_33.cube").size == 33
    with Image.open(folder / "previews" / "img_1.jpg") as im:
        assert im.size == (360, 240)
    assert _snapshot(refs) | _snapshot(mine) == before  # photos untouched


def test_run_refuses_to_overwrite(tmp_path: Path, folders: tuple[Path, Path]) -> None:
    refs, mine = folders
    run(refs, mine, out=tmp_path)  # named after the reference folder
    assert (tmp_path / "refs look" / "look.json").is_file()
    with pytest.raises(ValueError, match="already exists"):
        run(refs, mine, out=tmp_path)
    run(refs, mine, out=tmp_path, overwrite=True)

    other = tmp_path / "other"
    other.mkdir()
    (other / "notes.txt").write_text("mine")
    with pytest.raises(ValueError, match="isn't a lookmatch look"):
        run(refs, mine, name="other", out=tmp_path, overwrite=True)
    assert (other / "notes.txt").read_text() == "mine"


def test_run_never_writes_among_your_photos(folders: tuple[Path, Path]) -> None:
    refs, mine = folders
    for name, out in [("mine", mine.parent), (mine.parent.name, mine.parent.parent)]:
        with pytest.raises(ValueError, match="contains some of your photos"):
            run(refs, mine, name=name, out=out)


def test_file_stem() -> None:
    assert file_stem('a/b\\c:d*e?"f"<g>|h') == "a b c d e f g h"
    assert file_stem("日系 清新") == "日系 清新"
    assert file_stem(" ... ") == "look"


def test_cli_fit(tmp_path: Path, folders: tuple[Path, Path]) -> None:
    refs, mine = folders
    out = tmp_path / "out"
    args = ["fit", str(refs), str(mine), "--name", "Airy", "--out", str(out)]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert 'The look "Airy" is in' in result.output
    assert "report.html" in result.output
    assert (out / "Airy" / "Airy_33.cube").is_file()

    again = runner.invoke(app, args)
    assert again.exit_code == 1
    assert "already exists" in again.output
    assert "Traceback" not in again.output


def test_cli_missing_folder(tmp_path: Path) -> None:
    result = runner.invoke(app, ["fit", str(tmp_path / "nope"), str(tmp_path)])
    assert result.exit_code == 1
    assert "Can't find" in result.output


def test_cli_fit_help() -> None:
    result = runner.invoke(app, ["fit", "--help"])
    assert result.exit_code == 0
    assert "--portrait" in result.output
