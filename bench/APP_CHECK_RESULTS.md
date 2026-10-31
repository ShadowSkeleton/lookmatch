# App check results (task 1.5)

Do Photoshop and DaVinci Resolve apply a lookmatch `.cube` the same way
lookmatch does? Method and steps: [docs/qa-app-check.md](../docs/qa-app-check.md).

**Test:** `tests/fixtures/test_chart.png` with `tests/fixtures/test_look_33.cube`,
69 flat patches measured (center median), compared in 8-bit levels (0 to 255).
**Pass:** every patch within 2 levels.

## 2026-10-31

| App | Settings | Largest difference | Average | Verdict |
|---|---|---|---|---|
| Adobe Photoshop | Color Lookup adjustment layer, embedded profile kept, 8-bit, Save a Copy as PNG | 0 levels | 0.00 | PASS (identical) |
| DaVinci Resolve 21 (free) | DaVinci YRGB, Rec.709 Gamma 2.4, trilinear, data levels full, 1280 x 1020 timeline, Grab Still export | 1 level | 0.39 | PASS |

Notes:

- Photoshop's result is pixel-for-pixel identical to lookmatch on every patch,
  including the gray ramp, all 24 ColorChecker patches and pure primaries.
- Resolve is 1 level lower on some dark gray patches (for example gray 01:
  lookmatch `[10, 3, 0]`, Resolve `[9, 3, 0]`). That pattern fits Resolve
  rounding down where lookmatch rounds to nearest. It is invisible.
- Conclusion: lookmatch's color pipeline (sRGB-encoded LUT domain, red
  fastest in the file, trilinear interpolation) matches both apps. No color
  space assumptions need fixing before Phase 2.
- Lightroom Classic is checked separately in task 5.3, since it only takes a
  LUT inside a profile.

To rerun:

```bash
.venv/bin/python bench/app_check.py Photoshop=~/Desktop/lookmatch-qa/photoshop.png Resolve=~/Desktop/lookmatch-qa/resolve/default_1.1.1.png
```
