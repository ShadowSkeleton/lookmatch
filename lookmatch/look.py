"""Look dataclass and look.json read/write.

look.json records everything needed to reproduce a look: the lookmatch
version, the random seed, the settings, every photo used (by file name and
SHA-256 hash, so the exact file can be identified without storing its
folder), what was measured for each photo, and every fitted parameter.

The file is plain UTF-8 JSON with no timestamps, so the same inputs always
give a byte-identical file. Floats are written at full precision and read
back exactly.

Each fitting step adds its parameters here when it is built; the schema
version goes up whenever the format changes.
"""

import hashlib
import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import numpy as np

from lookmatch import __version__
from lookmatch.io import DEFAULT_SEED, jpeg_quality
from lookmatch.neutralize import Correction, Estimate
from lookmatch.toning import ZONES, SplitToning

# Format history. Older files still load and are upgraded on save.
#   1: photos, neutralization, tone curve
#   2: + split_toning
#   3: + photo width, height and jpeg_quality; warnings have a code
SCHEMA_VERSION = 3
TONE_CURVE_SAMPLES = 256

ROLES = ("reference", "input")
SOURCES = ("raw", "rendered")  # decoded by lookmatch, or exported by an editor


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 hash of a file, read in 1 MB chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _triple(values: Any, what: str) -> list[float]:
    out = [float(v) for v in values]
    if len(out) != 3:
        raise ValueError(f"{what} needs 3 values (red, green, blue), got {len(out)}.")
    return out


@dataclass
class Photo:
    """One photo used to fit a look, and what was measured from it."""

    file: str  # file name only, never the folder
    sha256: str
    role: str  # "reference" or "input"
    source: str  # "raw" or "rendered"
    illuminant: list[float]  # measured light color, linear RGB, luminance 1
    median_luminance: float
    reliable: bool
    white_balance: list[float]  # correction gains toward the group average
    exposure: float  # correction gain toward the group average
    width: int | None = None  # pixels, upright; None in files before format 3
    height: int | None = None
    jpeg_quality: int | None = None  # estimated, 1 to 100; None if not JPEG

    def __post_init__(self) -> None:
        """Validate the photo record."""
        if self.role not in ROLES:
            raise ValueError(
                f"A photo's role must be one of {ROLES}, got {self.role!r}."
            )
        if self.source not in SOURCES:
            raise ValueError(
                f"A photo's source must be one of {SOURCES}, got {self.source!r}."
            )
        self.illuminant = _triple(self.illuminant, "illuminant")
        self.white_balance = _triple(self.white_balance, "white_balance")
        self.median_luminance = float(self.median_luminance)
        self.exposure = float(self.exposure)

    @classmethod
    def from_estimate(
        cls,
        path: str | Path,
        role: str,
        source: str,
        estimate: Estimate,
        correction: Correction,
        size: tuple[int, int] | None = None,
    ) -> "Photo":
        """Build a record from a photo file and its neutralization.

        ``size`` is the photo's (width, height) in pixels, upright.
        """
        path = Path(path)
        width, height = size if size is not None else (None, None)
        return cls(
            file=path.name,
            sha256=sha256_file(path),
            role=role,
            source=source,
            illuminant=estimate.illuminant.tolist(),
            median_luminance=estimate.median_luminance,
            reliable=estimate.reliable,
            white_balance=correction.white_balance.tolist(),
            exposure=correction.exposure,
            width=width,
            height=height,
            jpeg_quality=jpeg_quality(path),
        )


@dataclass(frozen=True)
class LookWarning:
    """A problem found during a run, for a person to read and act on."""

    code: str  # stable identifier, for programs (see checks.py)
    message: str  # plain words: what happened and what to do


@dataclass
class Look:
    """Everything lookmatch fitted for one look."""

    name: str
    seed: int = DEFAULT_SEED
    lookmatch_version: str = __version__
    schema_version: int = SCHEMA_VERSION
    settings: dict[str, Any] = field(default_factory=dict)
    photos: list[Photo] = field(default_factory=list)
    tone_curve: list[float] | None = None  # 256 samples of OKLab L, 0 to 1
    split_toning: SplitToning | None = None  # OKLab (a, b) offset per zone
    metrics: dict[str, float] = field(default_factory=dict)
    warnings: list[LookWarning] = field(default_factory=list)

    def validate(self) -> None:
        """Check the fitted values make sense, with a plain-language error."""
        if self.tone_curve is not None:
            curve = np.asarray(self.tone_curve, dtype=np.float64)
            if curve.shape != (TONE_CURVE_SAMPLES,):
                raise ValueError(
                    f"The tone curve needs {TONE_CURVE_SAMPLES} samples, got "
                    f"{curve.size}."
                )
            if not np.all(np.isfinite(curve)):
                raise ValueError("The tone curve contains NaN or infinite values.")
            if np.any(np.diff(curve) < 0):
                raise ValueError(
                    "The tone curve must never go down: a brighter input must "
                    "never come out darker."
                )
        if self.split_toning is not None and not np.all(
            np.isfinite(self.split_toning.as_array())
        ):
            raise ValueError("The split toning contains NaN or infinite values.")


_ORDER = [
    "schema_version",
    "lookmatch_version",
    "seed",
    "name",
    "settings",
    "photos",
    "tone_curve",
    "split_toning",
    "metrics",
    "warnings",
]


def look_to_dict(look: Look) -> dict[str, Any]:
    """Return the look as plain JSON-ready data, in a fixed key order."""
    data = {
        "schema_version": look.schema_version,
        "lookmatch_version": look.lookmatch_version,
        "seed": look.seed,
        "name": look.name,
        "settings": dict(look.settings),
        "photos": [
            {f.name: getattr(p, f.name) for f in fields(Photo)} for p in look.photos
        ],
        "tone_curve": None
        if look.tone_curve is None
        else [float(v) for v in look.tone_curve],
        "split_toning": None
        if look.split_toning is None
        else {z: [float(v) for v in getattr(look.split_toning, z)] for z in ZONES},
        "metrics": {k: float(v) for k, v in look.metrics.items()},
        "warnings": [{"code": w.code, "message": w.message} for w in look.warnings],
    }
    assert list(data) == _ORDER
    return data


def save_look(look: Look, path: str | Path) -> None:
    """Validate a look and write it as look.json."""
    look.validate()
    try:
        text = json.dumps(
            look_to_dict(look), indent=2, ensure_ascii=False, allow_nan=False
        )
    except ValueError:
        raise ValueError(
            "The look contains NaN or infinite values, so it can't be saved. "
            "This is a bug in lookmatch; please report it."
        ) from None
    Path(path).write_text(text + "\n", encoding="utf-8")


def _warning(item: Any) -> LookWarning:
    if isinstance(item, str):  # format 2 and earlier: plain text
        return LookWarning(code="note", message=item)
    return LookWarning(code=str(item["code"]), message=str(item["message"]))


def load_look(path: str | Path) -> Look:
    """Read and validate a look.json file."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Can't find the look file '{path}'. Check the path.")
    bad = f"'{path.name}' isn't a valid look.json file"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        raise ValueError(f"{bad}: {err}.") from None
    if not isinstance(data, dict):
        raise ValueError(f"{bad}: it should hold one JSON object.")

    version = data.get("schema_version")
    if not isinstance(version, int):
        raise ValueError(f"{bad}: it has no schema_version.")
    if version > SCHEMA_VERSION:
        raise ValueError(
            f"'{path.name}' was made by a newer version of lookmatch (format "
            f"{version}; this version reads up to {SCHEMA_VERSION}). Update "
            "lookmatch to open it."
        )
    unknown = sorted(set(data) - set(_ORDER))
    if unknown:
        raise ValueError(f"{bad}: unknown fields {', '.join(unknown)}.")

    try:
        photos = [Photo(**p) for p in data.get("photos", [])]
        toning = data.get("split_toning")
        if toning is not None:
            toning = SplitToning(
                **{z: (float(toning[z][0]), float(toning[z][1])) for z in ZONES}
            )
        look = Look(
            name=data["name"],
            seed=data["seed"],
            lookmatch_version=data["lookmatch_version"],
            schema_version=SCHEMA_VERSION,  # older files are upgraded
            settings=data.get("settings", {}),
            photos=photos,
            tone_curve=data.get("tone_curve"),
            split_toning=toning,
            metrics=data.get("metrics", {}),
            warnings=[_warning(w) for w in data.get("warnings", [])],
        )
    except (KeyError, TypeError, IndexError) as err:
        raise ValueError(f"{bad}: missing or wrong field ({err}).") from None
    look.validate()
    return look
