"""Command line interface for lookmatch."""

import typer

from lookmatch import __version__

app = typer.Typer(
    help="Match the color look of a reference photo and apply it to your photos.",
    no_args_is_help=True,
    add_completion=False,
)


def _print_version(value: bool) -> None:
    """Print the installed version and exit."""
    if value:
        typer.echo(f"lookmatch {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        help="Show the installed version and exit.",
        callback=_print_version,
        is_eager=True,
    ),
) -> None:
    """Match the color look of a reference photo and apply it to your photos."""
