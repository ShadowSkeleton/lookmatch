# Benchmark

How close does lookmatch get to a look, compared with simpler methods? The
benchmark answers with numbers, so every change to lookmatch can be judged by
evidence instead of by eye.

## The idea

You can't measure "did it match the look?" on a real master shot, because
nobody knows the exact right answer. So the benchmark makes looks whose
answer *is* known:

1. Take a known look L (a LUT).
2. Apply L to some of your photos. These play "another photographer's graded
   photos": the references.
3. Give each method the references and your *other* photos. Each one builds a
   LUT.
4. Apply that LUT to your photos and compare with the right answer, L applied
   to the same photos, pixel by pixel with **ΔE 2000**, the standard measure
   of visible color difference (below about 1 is invisible).

Two conditions are measured:

- **Different scenes**: references and inputs are different photos. This is
  the real use case.
- **Same scenes**: references are L applied to the input photos themselves.
  The easy case, an upper bound on accuracy.

Methods compared: **no change** (any method worse than this makes photos
worse), **Reinhard** color transfer, **plain optimal transport**, and
**lookmatch**. See [docs/method.md](../docs/method.md).

## Run it

Put 15 to 30 varied photos in one folder (JPEG, PNG, TIFF or camera RAW;
landscapes, city, indoor, people, different light), then:

```bash
.venv/bin/python bench/benchmark.py --photos ~/Pictures/lookmatch-test
```

It writes [RESULTS.md](RESULTS.md) (readable tables) and `results.json`
(every single score). `--quick` runs 3 looks and 1 split for a fast check.

Notes:

- Photos are read at 800 px on the long side to keep runs short.
- For RAW files, the camera's own JPEG preview is used, standing in for an
  unedited export from your editor.
- Photos are only read. Nothing is changed, and no photo is copied into the
  repo. Scratch files go to `bench/work/`, which git ignores.

## Looks

The built-in looks are formulas in [make_looks.py](make_looks.py); see
[looks/README.md](looks/README.md). Some use the same building blocks as
lookmatch and may flatter it, so results are also reported per look. Add your
own `.cube` looks to `bench/looks/` and they are included automatically.

## Other files

- [app_check.py](app_check.py) and [APP_CHECK_RESULTS.md](APP_CHECK_RESULTS.md):
  task 1.5, checking that Photoshop and Resolve apply a lookmatch LUT exactly
  like lookmatch does.
