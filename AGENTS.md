# lookmatch: project brief for AI assistants

## What this is
lookmatch is an open-source Python tool that measures the color look of one
or more reference photos and builds a LUT that gives the user's photos that
look. It exports the look to multiple editing apps. It has three interfaces
over one engine:
1. Python package (the engine, all real logic lives here)
2. CLI: `lookmatch fit REFERENCE INPUTS --name NAME [--portrait]`
   - REFERENCE: one photo, or a folder of photos that share the same look
     (for example one photographer's series, or one film stock)
   - INPUTS: a folder of the user's own photos
3. Agent layer: a SKILL.md (Claude Code, Codex, Cursor) and an optional MCP server

## Goal: one universal LUT, not a 1:1 match
The output is one LUT that maps "the user's camera and editing app's typical
colors" to "the reference look", so it works on photos it has never seen.
- Pool all INPUTS photos to learn the user's typical starting colors. Pool all
  REFERENCE photos to learn the target look.
- Each photo counts equally: every photo contributes the same number of
  samples (up to the cap), so one large or unusual photo can't dominate.
- Neutralize each photo (white balance, exposure) before pooling, so the LUT
  learns the look, not each photo's lighting. Correct each photo toward its
  *group's* shared average (references as one group, inputs as another), not
  toward absolute gray: that keeps a reference look's overall cast as part
  of the look. A single photo is left unchanged.
- Per-photo problems (one wrong white balance) are not the LUT's job; the
  user fixes those in their editor.

## Input rendering (how the user's photos are read)
A LUT is applied to the image *after* the editing app renders the RAW, so the
fit must see the user's photos rendered the same way. Two paths, both
supported:
1. Recommended, most accurate: unedited exports from the user's editor
   (JPEG or 16-bit TIFF, same profile they edit with). The LUT sees exactly
   what it learned from.
2. Convenient: RAW files decoded directly by lookmatch (rawpy, neutral
   rendering). This only approximates the editor's rendering, so lookmatch
   warns that results may differ slightly in the app.
The report states which path was used. Mixing both in one INPUTS folder
triggers a warning.

## Core principle (most important rule)
Every number in the output comes from measurement or optimization.
No LLM, vision model, or neural network ever produces slider values,
curves, or LUT data. The agent layer only orchestrates, reads reports,
and picks options. Results must be deterministic (fixed random seed).

## Audience and product goals
lookmatch should be scientific, safe, quick, and easy to use. It is not only
for developers: photographers who have never used a terminal should be able
to learn it and use it.
- Every user-facing text (CLI help, errors, warnings, report.html, README,
  docs) uses plain language. Explain what happened and what to do next, in
  photographer terms. Keep the math in docs/method.md.
- Defaults must give a good result with no extra flags.
- Never overwrite or modify the user's original photos.
- report.html and any other UI follow a clean, minimal design that also
  works on a phone.

## Non-goals (do not build these)
- No masks, denoise, retouching, culling, or AI enhancement
- No GUI app in v1
- No neural networks or trained models
- No cloud service or API keys

## Color pipeline (v1 definitions)
- LUT domain: display-referred, sRGB-encoded RGB in [0,1] in and out
- Fitting math: linear sRGB primaries
- Perceptual comparisons: OKLab / OKLCh
- RAW input: decode with rawpy to linear sRGB with camera white balance, no
  auto brightening and no tone curve ("neutral rendering"), encode sRGB.
  See "Input rendering" above for when this is used.
- Reference input: JPEG/PNG/TIFF; embedded profiles converted to sRGB,
  sRGB assumed if no profile
- Pixel sampling: up to 100,000 pixels per image, seed = 0

## Pipeline steps
0. Load + normalize: decode, convert to working spaces, sample pixels from
   every reference and input photo
1. Neutralize: estimate white balance (gray world + white patch, blended)
   and exposure (median luminance) for each reference and input photo;
   move each photo to its group's shared average (white balance fully,
   exposure at half strength capped at 1 stop), then pool the reference
   samples and the input samples. See docs/method.md.
2. Decompose the look. Each part has a safe fit (holds up when the
   references show other scenes) and a full fit (precise for similar
   scenes); they are blended by the scene match (scenes.py): the larger of
   the fraction of references that are graded copies of input photos
   (rank correlation of lightness thumbnails >= 0.97) and
   exp(-(d/0.02)^2), where d is the OKLab sliced Wasserstein distance after
   the safe fit. See "When the scenes differ" in docs/method.md.
   a. Tone curve: safe = black and white points only (0.5% / 99.5%
      quantiles); full = histogram matching on OKLab L, then isotonic
      regression, then PCHIP interpolation. 256 samples, must be monotonic
   b. Split toning: weighted least squares fit of OKLab a/b offsets for
      shadows / midtones / highlights with smooth zone weights. Safe = per
      bin most common color (mean shift), shrunk by how much the reference
      photos agree (empirical Bayes); full = per bin average color
   c. Residual color: sliced optimal transport in OKLab, strength =
      scene match (only the full fit)
   d. Skin constraint (opt-in with `--portrait`, off by default): YCbCr
      rule-based skin mask; skin hue in OKLCh may drift at most a threshold
      (default 6 degrees). Off by default because a color-only rule can't
      tell skin from skin-colored scenery: on desert landscapes it marked
      40-68% of the pixels as skin. Skin hue drift is still measured and
      reported on every run.
3. Bake: 33x33x33 LUT fit by sparse least squares with trilinear
   interpolation weights + Laplacian smoothness term. Cells with no samples
   fall back to steps 2a+2b only (not identity). Check monotonic L, clip gamut.
4. Verify: compute metrics (see below), write report
5. Export: write all target formats

## Metrics
- Sliced Wasserstein distance (OKLab) between output and reference
- Histogram distance on OKLab L
- Skin hue drift (degrees, mean and p95)
- SSIM on luminance, output vs input (artifact check)
- LUT total variation (smoothness)
- Benchmark only: mean and p95 Delta E 2000 vs ground truth

## Outputs of one run (folder NAME/)
- NAME_33.cube            Adobe/IRIDAS .cube, LUT_3D_SIZE 33, red changes fastest
- NAME_hald.png           Hald CLUT level 8 (512x512)
- NAME_preset.xmp         Lightroom/ACR preset: tone curve (master point curve) +
                          split toning (R/G/B point curves). Color Grading
                          wheels need a Lightroom measurement first.
- LIGHTROOM_PROFILE.md    steps to turn the .cube into a LR profile via Camera Raw
- look.json               every fitted parameter + version + seed (reproducible)
- report.html             before/after grid, curves, metrics, warnings
- previews/               input photos with the look applied

## Warnings the tool must raise
- Reference and input scene content too different (color distribution distance
  above threshold, or very different luminance histograms)
- Skin drift above threshold (without `--portrait`: suggest it if the
  photos have people; with it: say how much was held back)
- Reference looks heavily compressed or tiny (< 800 px short side)
- Reference photos disagree with each other a lot (they may not share one look).
  Not built yet: the per-photo tint spread depends more on scene content than
  on the look (docs/method.md, "Checking the result"); needs a better measure
- Too few input photos to generalize (default: fewer than 5)
- Input photos were decoded from RAW directly (approximation of the editor)
- INPUTS mixes RAW files and rendered exports

## Tech stack (only these dependencies)
Python 3.11+. Runtime: numpy, scipy, scikit-image, colour-science, POT,
rawpy, pillow, typer (CLI), jinja2 (report), matplotlib (report plots).
Optional extras: mcp (MCP server), opencv-python, mediapipe.
Dev: pytest, ruff, mypy.
Never add a dependency outside this list without asking first.

## License rules
- Project license: MIT (copyright Jackson Feng)
- Never copy code from repos without a confirmed permissive license
  (MIT, BSD, Apache-2.0). Specifically do NOT copy from ColorMatch3D,
  mini-film, or the Adobe DNG SDK.
- Do not vendor or modify LibRaw.
- MIT-Adobe FiveK images: benchmark use only, never commit them, never put
  them in README or demos. Only a download script and result numbers.
- README and demo images: only the maintainer's own photos.
- Algorithms from papers (Reinhard, Pitie sliced OT) are implemented from
  the paper, with citations in docs.

## File format rules
- Never guess file format fields. For Lightroom XMP fields, use a real
  preset exported from Lightroom (in tests/fixtures/) as the reference.
- .cube must follow the Adobe Cube LUT spec 1.0 (TITLE, LUT_3D_SIZE,
  DOMAIN_MIN, DOMAIN_MAX).

## Repo structure
lookmatch/
  lookmatch/
    __init__.py
    io.py          load images/RAW, sampling, color space conversion
    neutralize.py  white balance + exposure normalization
    tone.py        tone curve fitting
    toning.py      split toning fit
    transport.py   sliced optimal transport
    skin.py        skin mask + constraint
    bake.py        LUT fitting with smoothness
    apply.py       apply LUT (trilinear) to images
    metrics.py     all metrics
    checks.py      warnings (codes + plain-language messages)
    report.py      report.html (template in templates/report.html)
    look.py        Look dataclass + look.json read/write
    pipeline.py    fit(): every step in order, returns Look + LUT
    scenes.py      scene match: graded copies + color distance
    baselines.py   no change, Reinhard, plain OT (for the benchmark)
    export/
      cube.py  hald.py  lr_preset.py  lr_profile_guide.py
    cli.py
    mcp_server.py
  skills/lookmatch/SKILL.md
  bench/           benchmark.py (known looks, ΔE 2000), make_looks.py,
                   RESULTS.md, app_check.py; see bench/README.md
  tests/           pytest, fixtures/
  docs/            method.md (math + citations), apps.md (per-app install)
    figures/       README figures + make_figures.py (real lookmatch output only)
  README.md  README.zh-CN.md  LICENSE  pyproject.toml  AGENTS.md  CLAUDE.md

## Development setup
```bash
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest && .venv/bin/ruff check . && .venv/bin/mypy
```

## Coding standards
- Type hints everywhere, docstrings on public functions
- Pure functions for math; no global state
- Full images may be float32 to save memory, but compute statistics and fits
  in float64 (use `io.sample_pixels`, or `dtype=np.float64` in reductions).
  float32 sums over a large photo are badly wrong.
- Every module has tests; math tests use synthetic images with known answers
- ruff + mypy clean, pytest passing before any commit
- Keep functions small; explain any formula with a comment and citation

## Definition of done for any task
1. Code + tests written
2. `pytest`, `ruff check`, `mypy` all pass
3. Any new behavior documented in docs/ or README
4. No new dependency, no copied code, no guessed file format fields
5. User-facing text is understandable by a photographer who is not a developer
