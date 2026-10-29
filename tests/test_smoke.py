from typer.testing import CliRunner

import lookmatch
from lookmatch.cli import app

runner = CliRunner()


def test_version_is_set() -> None:
    assert lookmatch.__version__


def test_cli_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "reference photo" in result.output


def test_cli_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert lookmatch.__version__ in result.output
