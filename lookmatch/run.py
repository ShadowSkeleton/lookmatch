"""One complete run: fit a look and write its folder.

run() is what `lookmatch fit` does, and what the agent layer calls. It fits
the look (pipeline.fit), then writes one folder named after the look:

    NAME/
      NAME_33.cube          the LUT
      NAME_hald.png         the same LUT as a Hald image
      NAME_preset.xmp       Lightroom / Camera Raw preset
      LIGHTROOM_PROFILE.md  how to turn the LUT into a Lightroom profile
      look.json             everything measured and fitted
      report.html           before and after, the look in words, warnings
      previews/             your photos with the look, as JPEG

Your photos are only read, never written. The folder is new, or, with
``overwrite``, a folder lookmatch made before; anything else is refused.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from lookmatch import pipeline, report
from lookmatch.export import cube, hald, lr_preset, lr_profile_guide
from lookmatch.look import Look, save_look

PREVIEW_QUALITY = 90
LOOK_FILE = "look.json"
REPORT_FILE = "report.html"
PREVIEW_FOLDER = "previews"

# Characters that no file name may hold on Windows, macOS or Linux.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

Progress = Callable[[str], None]


@dataclass(frozen=True)
class RunResult:
    """What a run wrote."""

    look: Look
    folder: Path
    files: list[str]  # file names inside the folder, in the order written


def file_stem(name: str) -> str:
    """Make a look's name safe to use in file names, keeping any language."""
    stem = " ".join(_UNSAFE.sub(" ", name).split()).strip(". ")
    return stem or "look"


def _quiet(_: str) -> None:
    pass


def _check_folder(folder: Path, photos: list[Path], overwrite: bool) -> None:
    """Refuse folders that could hold your photos or someone else's files."""
    resolved = folder.resolve()
    for photo in photos:
        if resolved == photo.resolve().parent or resolved in photo.resolve().parents:
            raise ValueError(
                f"The output folder '{folder}' contains some of your photos "
                f"({photo.name}). Choose another output folder, so lookmatch "
                "can't touch your photos."
            )
    if folder.exists() and not folder.is_dir():
        raise ValueError(f"'{folder}' is a file, not a folder. Choose another name.")
    if folder.is_dir() and any(folder.iterdir()):
        if not overwrite:
            raise ValueError(
                f"The folder '{folder}' already exists. Choose another name "
                "with --name, or use --overwrite to replace the look in it."
            )
        if not (folder / LOOK_FILE).is_file():
            raise ValueError(
                f"The folder '{folder}' isn't a lookmatch look (it has no "
                f"{LOOK_FILE}), so lookmatch won't write into it. Choose "
                "another name."
            )


def _preview_names(photos: list[Path]) -> list[str]:
    """One JPEG name per photo; photo.jpg and photo.ARW get distinct names."""
    stems = [p.stem for p in photos]
    return [
        f"{p.stem}.jpg" if stems.count(p.stem) == 1 else f"{p.stem}_{p.suffix[1:]}.jpg"
        for p in photos
    ]


def _write_previews(
    photos: list[Path], lut: cube.Cube, folder: Path, progress: Progress
) -> tuple[list[report.Preview], list[float]]:
    """Write a preview of each photo; return the first few, and every SSIM.

    Photos are processed one at a time, so memory stays low with many photos.
    """
    folder.mkdir(parents=True, exist_ok=True)
    shown: list[report.Preview] = []
    ssims: list[float] = []
    for i, (photo, out_name) in enumerate(
        zip(photos, _preview_names(photos), strict=True), start=1
    ):
        progress(f"Previewing your photos ({i} of {len(photos)}): {photo.name}")
        (preview,) = report.make_previews([photo], lut)
        Image.fromarray(preview.after).save(
            folder / out_name, "JPEG", quality=PREVIEW_QUALITY, optimize=True
        )
        ssims.append(preview.ssim)
        if len(shown) < report.MAX_PREVIEWS:
            shown.append(preview)
    return shown, ssims


def run(
    reference: pipeline.PhotoSource,
    inputs: pipeline.PhotoSource,
    name: str | None = None,
    out: str | Path = ".",
    portrait: bool = False,
    overwrite: bool = False,
    progress: Progress = _quiet,
) -> RunResult:
    """Fit a look and write its folder inside ``out``. See the module docs.

    ``name`` defaults to the reference folder's (or photo's) name plus
    "look", so the look's folder is never the reference folder itself.
    """
    ref_photos = pipeline.collect_photos(reference)
    my_photos = pipeline.collect_photos(inputs)
    if name is None:
        source = Path(reference).stem if isinstance(reference, (str, Path)) else ""
        name = f"{source} look".strip()
    stem = file_stem(name)
    folder = Path(out) / stem
    _check_folder(folder, ref_photos + my_photos, overwrite)

    progress(
        f"Measuring {len(ref_photos)} reference photos and {len(my_photos)} of "
        "your photos"
    )
    result = pipeline.fit(ref_photos, my_photos, name=name, portrait=portrait)
    look = result.look
    folder.mkdir(parents=True, exist_ok=True)

    files = [f"{stem}_33.cube", f"{stem}_hald.png", f"{stem}_preset.xmp"]
    progress("Writing the LUT and presets")
    cube.write_cube(folder / files[0], result.cube)
    hald.write_hald(folder / files[1], result.cube)
    lr_preset.write_preset(folder / files[2], look)
    lr_profile_guide.write_guide(folder, name, files[0], files[2])
    files.append(lr_profile_guide.GUIDE_NAME)

    previews, ssims = _write_previews(
        my_photos, result.cube, folder / PREVIEW_FOLDER, progress
    )
    look.metrics.update(report.ssim_summary(ssims))
    save_look(look, folder / LOOK_FILE)
    files += [LOOK_FILE, f"{PREVIEW_FOLDER}/"]

    progress("Writing the report")
    report.write_report(
        folder / REPORT_FILE, look, previews, [*files, REPORT_FILE], len(my_photos)
    )
    files.append(REPORT_FILE)
    return RunResult(look=look, folder=folder, files=files)
