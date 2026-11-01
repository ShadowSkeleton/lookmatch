"""Command line interface for lookmatch."""

import textwrap
from pathlib import Path
from typing import Annotated

import typer

from lookmatch import __version__, run

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


_FILE_NOTES = {
    "_33.cube": "the look as a LUT: Photoshop, DaVinci Resolve and most apps",
    "_hald.png": "the same LUT as an image: RawTherapee, darktable",
    "_preset.xmp": "Lightroom and Camera Raw preset (editable, close to the look)",
    "LIGHTROOM_PROFILE.md": "how to use the exact look in Lightroom",
    "look.json": "everything lookmatch measured, to reproduce this look",
    "previews/": "your photos with the look",
    "report.html": "open this first: before and after, and what the look does",
}


def _note(file: str) -> str:
    return next((note for end, note in _FILE_NOTES.items() if file.endswith(end)), "")


def _progress(message: str) -> None:
    typer.echo(f"  {message}", err=True)


@app.command()
def fit(
    reference: Annotated[
        Path,
        typer.Argument(
            help="The look you want: one photo, or a folder of photos that "
            "share the same look.",
            show_default=False,
        ),
    ],
    inputs: Annotated[
        Path,
        typer.Argument(
            help="A folder of your own photos, unedited: exports from your "
            "editor (recommended) or camera RAW files.",
            show_default=False,
        ),
    ],
    name: Annotated[
        str | None,
        typer.Option(
            "--name",
            "-n",
            help="Name of the look, used for its folder and files. "
            'Default: the reference folder\'s name plus "look".',
            show_default=False,
        ),
    ] = None,
    portrait: Annotated[
        bool,
        typer.Option(
            "--portrait",
            help="Keep skin tones natural. Use it when your photos have people.",
        ),
    ] = False,
    out: Annotated[
        Path,
        typer.Option(
            "--out",
            "-o",
            help="Where to make the look's folder.",
        ),
    ] = Path("."),
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            help="Replace a look made before with the same name.",
        ),
    ] = False,
) -> None:
    """Learn the look of REFERENCE and make a LUT and presets for your photos.

    Your photos are only read, never changed. Everything is written to a new
    folder named after the look.
    """
    try:
        result = run.run(
            reference,
            inputs,
            name=name,
            out=out,
            portrait=portrait,
            overwrite=overwrite,
            progress=_progress,
        )
    except (FileNotFoundError, ValueError) as err:
        typer.secho(f"\n{err}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from None

    typer.echo(f'\nDone. The look "{result.look.name}" is in {result.folder}/\n')
    width = max(len(f) for f in result.files)
    for file in result.files:
        typer.echo(f"  {file.ljust(width)}  {_note(file)}")
    if result.look.warnings:
        typer.echo("\nCheck these first:\n")
        for warning in result.look.warnings:
            typer.echo(
                textwrap.fill(
                    warning.message, 76, initial_indent="  - ", subsequent_indent="    "
                )
                + "\n"
            )
