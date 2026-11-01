from pathlib import Path

from lookmatch.export.lr_profile_guide import GUIDE_NAME, write_guide


def test_guide_names_the_look_and_its_files(tmp_path: Path) -> None:
    path = write_guide(tmp_path, "雪天人像", "雪天人像_33.cube", "雪天人像_preset.xmp")
    assert path == tmp_path / GUIDE_NAME
    text = path.read_text(encoding="utf-8")
    assert "雪天人像_33.cube" in text and "雪天人像_preset.xmp" in text
    assert "**Name:** 雪天人像" in text
    assert "sRGB" in text  # the one setting that must not be wrong
