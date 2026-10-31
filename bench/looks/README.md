# Benchmark looks

The benchmark always uses its built-in looks, defined as formulas in
`bench/make_looks.py`:

| Look | What it does | Same building blocks as lookmatch? |
|---|---|---|
| `warm_cool_test` | Warm shadows, cool highlights, gentle S-curve (the test look) | Yes |
| `teal_orange` | Teal shadows, orange highlights, more contrast and saturation | Yes |
| `faded_film` | Lifted blacks, muted color, warm highlights | Yes |
| `cool_moody` | Darker, desaturated, blue shadows | Yes |
| `golden_hour` | Warm overall, brighter, richer color | Mostly |
| `bleach_bypass` | Strong contrast, little color | Mostly |
| `green_to_teal` | Only greens change: toward teal, less saturated | No (hue-selective) |
| `channel_mix` | Cross-channel mix in linear light, like some film emulations | No |

Looks built from the same pieces lookmatch fits may flatter it, so the
benchmark reports every look separately.

## Adding your own looks

Put `.cube` files you made yourself in this folder (for example graded in
DaVinci Resolve or Lightroom and exported). The benchmark picks them up
automatically. Only add looks you made, or whose license allows it, and note
where each came from below.

| File | Made by | How |
|---|---|---|
