# look.json: the record of a look

Every time lookmatch fits a look, it writes `look.json` next to the LUT and
presets. It records everything needed to make the exact same look again, and
to check how it was made.

You never need to edit it. Keep it with your LUT: if a look ever comes out
differently, this file shows what changed.

## Why it matters

- **Reproducible.** With the same photos, the same lookmatch version and the
  same seed, lookmatch makes a byte-identical `look.json` and the same LUT.
  There are no timestamps or random parts in the file.
- **Traceable.** Each photo is listed by file name and SHA-256 hash, a
  fingerprint of the file's exact contents. If someone edits or re-exports a
  photo, its hash changes, so you can tell whether a rerun really used the
  same files.
- **Private.** Only the file name is stored, never the folder it was in.

## What's inside

| Field | What it holds |
|---|---|
| `schema_version` | Version of this file format (currently 3) |
| `lookmatch_version` | The lookmatch version that made the look |
| `seed` | The random seed used for pixel sampling (0) |
| `name` | The look's name (any language, saved as UTF-8) |
| `settings` | Every setting used, such as LUT size |
| `photos` | One entry per photo, see below |
| `tone_curve` | The fitted tone curve: 256 lightness values (OKLab L) from shadows to highlights, never going down |
| `split_toning` | The tint added to `shadows`, `midtones` and `highlights`: each an OKLab `[a, b]` offset (a: green to red, b: blue to yellow) |
| `metrics` | Everything measured: how alike the scenes are, how much closer the colors came to the references, skin hue change, picture quality (SSIM) and LUT smoothness |
| `warnings` | Every warning from the run: a `code` for programs (listed in `lookmatch/checks.py`) and a `message` in plain words |

Each entry in `photos`:

| Field | What it holds |
|---|---|
| `file`, `sha256` | File name and fingerprint |
| `role` | `reference` (the look you want) or `input` (your photos) |
| `source` | `rendered` (exported from an editor) or `raw` (decoded by lookmatch) |
| `illuminant` | The measured color of the light (linear RGB, scaled to brightness 1) |
| `median_luminance` | The photo's median brightness, used for exposure |
| `reliable` | `false` if the photo had too little information to measure its light |
| `white_balance`, `exposure` | The correction that moved this photo to its group's average (see [method.md](method.md)) |
| `width`, `height` | The photo's size in pixels, upright |
| `jpeg_quality` | Estimated JPEG quality, 1 to 100 (`null` if not a JPEG) |

More fields are added as each fitting step is built. When the format
changes, `schema_version` goes up: version 1 had photos and the tone curve,
version 2 added `split_toning`, version 3 added photo sizes, JPEG quality
and warning codes. Older files still open and are upgraded when
saved. An older lookmatch refuses a newer file with a clear message instead
of misreading it.

## Example

Shortened:

```json
{
  "schema_version": 3,
  "lookmatch_version": "0.1.0.dev0",
  "seed": 0,
  "name": "雪天人像（日系）",
  "settings": {"lut_size": 33},
  "photos": [
    {
      "file": "reference.jpg",
      "sha256": "9f2c…",
      "role": "reference",
      "source": "rendered",
      "illuminant": [1.08, 0.99, 0.96],
      "median_luminance": 0.155,
      "reliable": true,
      "white_balance": [1.0, 1.0, 1.0],
      "exposure": 1.0,
      "width": 4000,
      "height": 6000,
      "jpeg_quality": 92
    }
  ],
  "tone_curve": [0.0, 0.0041, "…"],
  "split_toning": {
    "shadows": [0.0137, 0.0404],
    "midtones": [-0.004, -0.0122],
    "highlights": [-0.0078, -0.0223]
  },
  "metrics": {"scene_match": 0.94, "color_distance_after": 0.012, "…": 0},
  "warnings": [
    {
      "code": "few_inputs",
      "message": "Only 3 of your photos were used. …"
    }
  ]
}
```
