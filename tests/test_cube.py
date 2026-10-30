from pathlib import Path

import numpy as np
import pytest

from lookmatch.export.cube import (
    Cube,
    identity_table,
    parse_cube,
    read_cube,
    write_cube,
)


def _data_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln and (ln[0].isdigit() or ln[0] == "-")]


# --- Identity ------------------------------------------------------------------


def test_identity_table_layout() -> None:
    t = identity_table(3)
    assert t.shape == (3, 3, 3, 3)
    # table[r, g, b] is the output color for input (r, g, b).
    np.testing.assert_array_equal(t[2, 1, 0], [1.0, 0.5, 0.0])
    np.testing.assert_array_equal(t[0, 0, 2], [0.0, 0.0, 1.0])


@pytest.mark.parametrize("size", [2, 17, 33, 65])
def test_identity_round_trips_exactly(tmp_path: Path, size: int) -> None:
    path = tmp_path / "identity.cube"
    write_cube(path, Cube(identity_table(size), title="identity"))
    back = read_cube(path)
    assert back.size == size
    assert back.title == "identity"
    np.testing.assert_array_equal(back.table, identity_table(size))


def test_random_table_round_trips(tmp_path: Path) -> None:
    table = np.random.default_rng(0).random((9, 9, 9, 3))
    path = tmp_path / "r.cube"
    write_cube(path, Cube(table))
    np.testing.assert_allclose(read_cube(path).table, table, atol=5e-7)


# --- Written file follows the Adobe Cube LUT spec 1.0 -------------------------


def test_written_header(tmp_path: Path) -> None:
    path = tmp_path / "h.cube"
    write_cube(path, Cube(identity_table(33), title="My Look"))
    lines = path.read_text().splitlines()
    keywords = [ln for ln in lines if ln and ln[0].isalpha()]
    assert keywords == [
        'TITLE "My Look"',
        "LUT_3D_SIZE 33",
        "DOMAIN_MIN 0.0 0.0 0.0",
        "DOMAIN_MAX 1.0 1.0 1.0",
    ]
    assert all(ln.startswith("#") for ln in lines[: lines.index(keywords[0])])
    assert len(_data_lines(path.read_text())) == 33**3
    assert path.read_bytes().endswith(b"\n")
    assert b"\r" not in path.read_bytes()


def test_red_changes_fastest(tmp_path: Path) -> None:
    path = tmp_path / "o.cube"
    write_cube(path, Cube(identity_table(33)))
    data = _data_lines(path.read_text())
    assert data[0] == "0.000000 0.000000 0.000000"
    assert data[1] == "0.031250 0.000000 0.000000"  # red moved
    assert data[33] == "0.000000 0.031250 0.000000"  # then green
    assert data[33 * 33] == "0.000000 0.000000 0.031250"  # then blue
    assert data[-1] == "1.000000 1.000000 1.000000"


def test_no_negative_zero_or_exponents(tmp_path: Path) -> None:
    table = identity_table(2)
    table[0, 0, 0] = [-0.0, 1e-9, 2.5]
    path = tmp_path / "z.cube"
    write_cube(path, Cube(table))
    first = _data_lines(path.read_text())[0]
    assert first == "0.000000 0.000000 2.500000"
    assert "e" not in path.read_text().split("LUT_3D_SIZE")[1].lower()


def test_title_is_made_safe(tmp_path: Path) -> None:
    path = tmp_path / "t.cube"
    write_cube(path, Cube(identity_table(2), title='Snow "portrait"\n雪天人像'))
    assert "TITLE \"Snow 'portrait'\"" in path.read_text().splitlines()
    path.read_text(encoding="ascii")  # whole file is plain ASCII

    write_cube(path, Cube(identity_table(2), title="雪天人像"))
    assert 'TITLE "lookmatch"' in path.read_text().splitlines()


def test_custom_domain_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "d.cube"
    cube = Cube(identity_table(2), domain_min=(-0.1, 0.0, 0.0), domain_max=(1.5, 1, 1))
    write_cube(path, cube)
    back = read_cube(path)
    assert back.domain_min == (-0.1, 0.0, 0.0)
    assert back.domain_max == (1.5, 1.0, 1.0)


# --- Reading files from other apps --------------------------------------------


def test_parse_lenient_formatting() -> None:
    text = (
        "﻿# made in some app\r\n"
        "\r\n"
        "LUT_3D_SIZE 2\r\n"
        'TITLE "Other app"\r\n'
        "LUT_3D_INPUT_RANGE 0.0 1.0\r\n"
        "# a comment between keywords\r\n"
        "0 0 0\r\n"
        "1\t0   0\r\n"
        "0 1 0\r\n"
        "1 1 0\r\n"
        "0 0 1\r\n"
        "1 0 1\r\n"
        "0 1 1\r\n"
        "1 1 1\r\n"
    )
    cube = parse_cube(text)
    assert cube.title == "Other app"
    np.testing.assert_array_equal(cube.table, identity_table(2))


def test_parse_input_range_sets_domain() -> None:
    body = "\n".join(["0 0 0"] * 8)
    cube = parse_cube(f"LUT_3D_SIZE 2\nLUT_3D_INPUT_RANGE -0.5 2.0\n{body}\n")
    assert cube.domain_min == (-0.5, -0.5, -0.5)
    assert cube.domain_max == (2.0, 2.0, 2.0)


def test_parse_defaults() -> None:
    body = "\n".join(["0.5 0.5 0.5"] * 8)
    cube = parse_cube(f"LUT_3D_SIZE 2\n{body}\n")
    assert cube.title == ""
    assert cube.domain_min == (0.0, 0.0, 0.0)
    assert cube.domain_max == (1.0, 1.0, 1.0)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("0 0 0\n", "LUT_3D_SIZE"),
        ("LUT_3D_SIZE 2\n0 0 0\n", "expected 8"),
        ("LUT_3D_SIZE 1\n0 0 0\n", "between 2 and 256"),
        ("LUT_3D_SIZE 2\n" + "0 0 x\n" * 8, "line 2"),
        ("LUT_3D_SIZE 2\n" + "0 0\n" * 8, "3 numbers"),
        ("LUT_1D_SIZE 4\n" + "0 0 0\n" * 4, "1D"),
        (
            "LUT_3D_SIZE 2\nDOMAIN_MIN 1 0 0\nDOMAIN_MAX 0 1 1\n" + "0 0 0\n" * 8,
            "DOMAIN",
        ),
        (
            "LUT_3D_SIZE 2\n" + "0 0 0\n" * 7 + "LUT_3D_SIZE 2\n0 0 0\n",
            "before the data",
        ),
    ],
)
def test_parse_errors_are_clear(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_cube(text)


def test_read_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Can't find"):
        read_cube(tmp_path / "missing.cube")


# --- Validation ----------------------------------------------------------------


def test_cube_rejects_bad_tables() -> None:
    with pytest.raises(ValueError, match="shape"):
        Cube(np.zeros((4, 4, 3, 3)))
    with pytest.raises(ValueError, match="between 2 and 256"):
        Cube(np.zeros((1, 1, 1, 3)))
    bad = identity_table(2)
    bad[0, 0, 0, 0] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        Cube(bad)
