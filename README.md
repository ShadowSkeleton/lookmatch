<p align="center">
  <b>English</b> · <a href="README.zh-CN.md">简体中文</a>
</p>

# lookmatch

[![CI](https://github.com/ShadowSkeleton/lookmatch/actions/workflows/ci.yml/badge.svg)](https://github.com/ShadowSkeleton/lookmatch/actions/workflows/ci.yml)

Give lookmatch one or more photos whose colors you love, plus a folder of your
own photos. It measures both and builds one LUT that gives your camera's
photos that look, including photos you take later. You get a LUT and presets
you can use in Lightroom, Photoshop, DaVinci Resolve, and other editing apps.

> **Status:** early development, not ready to use yet. The whole engine is
> built and tested, and a LUT from lookmatch looks identical in Photoshop and
> DaVinci Resolve. It matches a look well when the reference photos and your
> photos show similar scenes. When they show different scenes, it doesn't
> work yet: see [Benchmark](#benchmark). Star the repo to follow along.

## Built on measurement, not guessing

- **Every number is measured or optimized.** No AI model picks slider values,
  curves, or LUT colors. lookmatch measures the colors in your photos and the
  reference, then solves for the change between them.
- **Same photos, same result.** Random sampling uses a fixed seed, so a run
  is exactly repeatable.
- **Every step is checked.** Each part of the engine is tested against known
  answers and against independent libraries, on every change.
- **Methods come from published color science**, with citations in
  [docs/method.md](docs/method.md).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/pipeline_dark.svg">
  <img alt="The six steps: load, neutralize, measure the look, bake a 3D LUT, verify, export." src="docs/figures/pipeline_light.svg" width="100%">
</picture>

## See the engine work

These figures check the engine with a **hand-made test look**: warmer
shadows, cooler highlights and a gentle S-curve. Every figure is computed by
lookmatch itself ([docs/figures/make_figures.py](docs/figures/make_figures.py)).

**What the test look does, measured.** A gray ramp from black to white goes
through the LUT, and lookmatch measures the result in OKLab, a color space
built to match how people see color differences.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/tone_response_dark.svg">
  <img alt="Line chart. Warmth rises by about 2 OKLab units in the shadows and falls by about 2.5 in the highlights. Lightness drops by up to 3 in the shadows and rises by up to 3 in the highlights. Pure black and pure white stay unchanged." src="docs/figures/tone_response_light.svg" width="100%">
</picture>

**Learning a look from photos.** Left: your photo (the camera's own JPEG).
Middle: the target, a known teal-and-orange look. Right: the look lookmatch
learned from reference photos, with its default settings, applied to your
photo.

<img alt="Three versions of Horseshoe Bend. Left, the original. Middle, a teal-and-orange look with warm, peach-colored clouds. Right, lookmatch's result, nearly the same as the middle, with clouds a little less orange." src="docs/figures/photo_match.jpg" width="100%">

The target look is ΔE 6.15 away from the original; lookmatch's result is
ΔE 1.30 away from the target, which is barely noticeable even side by side
(1.30 to 2.35 across the three demo photos). This is the **easy case**: the
reference photos were these same scenes with the look applied. When the
references show different scenes, lookmatch doesn't work yet (see
[Benchmark](#benchmark)).

**On a test chart.** A gray ramp, the 24-patch ColorChecker and pure
primaries, before (left) and after (right).

<img alt="Test chart before and after the test look." src="docs/figures/chart_before_after.png" width="100%">

**Same result in your apps.** The same LUT, applied to the test chart in
Photoshop and DaVinci Resolve, was measured on all 69 patches: Photoshop
matches lookmatch exactly, and Resolve is within 1 level out of 255
([results](bench/APP_CHECK_RESULTS.md)).

## How it's tested

| What | Checked against | Tolerance |
|---|---|---|
| sRGB, linear and OKLab conversions | Round trip over 10,000 values | 0.0001 |
| OKLab values | colour-science (independent library) | 0.002 |
| Phone photos in Display P3 | colour-science conversion | 2 of 255 levels |
| `.cube` LUT files | Write, then read back | Exact |
| Applying a LUT | SciPy's interpolation | 0.000000000001 |
| Same LUT in Photoshop and Resolve | lookmatch's own result, 69 patches | 0 and 1 of 255 levels |
| Color difference (ΔE 2000) | Published test data (Sharma et al. 2005) | 0.0001 |
| Recovering a known tone curve | Synthetic photos | 0.41% |

All tests run on Python 3.11 and 3.12 for every change
([CI](https://github.com/ShadowSkeleton/lookmatch/actions/workflows/ci.yml)).

## Benchmark

To measure honestly, the benchmark uses looks whose exact answer is known: a
look is applied to some photos to make the "reference" photos, each method
builds a LUT from them, and the LUT is compared with the right answer on your
other photos using **ΔE 2000**, the standard measure of visible color
difference (below about 1, people can't see it). Details:
[bench/README.md](bench/README.md).

First results, on only 4 photos with 8 known looks
([full table](bench/RESULTS.md)). Mean ΔE 2000, lower is better:

| Method | Same scenes | Different scenes |
|---|---|---|
| No change | 4.67 | **4.67** |
| Reinhard color transfer | 2.91 | 13.60 |
| Plain optimal transport | **0.42** | 15.13 |
| lookmatch | 1.26 | 14.23 |

When the reference photos and your photos show the same scenes, matching
works well. When they show different scenes, every method, lookmatch
included, makes photos worse than doing nothing: it mistakes the difference
between scenes for a look. This is the main open problem, and the benchmark
exists to measure every attempt to solve it. With only 4 photos these numbers
are a first signal, not a conclusion.

## License

MIT, see [LICENSE](LICENSE).
