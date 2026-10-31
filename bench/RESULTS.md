# Benchmark results

How close each method gets to a known look, on photos it never saw as references. Score: mean ΔE 2000 against the right answer (below about 1 is invisible; lower is better). Method: [bench/benchmark.py](benchmark.py).

## Setup

- date: 2026-10-31
- lookmatch version: 0.1.0.dev0
- photos: 45
- photo size: 800 px long side
- looks: warm_cool_test, teal_orange, faded_film, cool_moody, golden_hour, bleach_bypass, green_to_teal, channel_mix
- folds: 3
- lookmatch transport strength: 0.5

## Different scenes

| Method | Mean ΔE 2000 | 95th percentile | Photos made worse than no change |
|---|---|---|---|
| no change | 4.51 | 7.13 | 0% |
| Reinhard | 7.97 | 13.44 | 84% |
| plain OT | 7.41 | 12.96 | 77% |
| lookmatch | 7.04 | 12.10 | 75% |

Mean ΔE 2000 per look:

| Look | no change | Reinhard | plain OT | lookmatch |
|---|---|---|---|---|
| warm_cool_test | 3.81 | 9.77 | 8.14 | 7.85 |
| teal_orange | 5.86 | 10.70 | 8.20 | 7.71 |
| faded_film | 3.84 | 6.47 | 6.69 | 6.19 |
| cool_moody | 6.44 | 8.68 | 6.90 | 6.43 |
| golden_hour | 9.04 | 8.15 | 7.92 | 7.34 |
| bleach_bypass | 5.20 | 6.03 | 6.48 | 6.91 |
| green_to_teal | 0.68 | 7.31 | 7.81 | 7.18 |
| channel_mix | 1.18 | 6.68 | 7.15 | 6.69 |

## Same scenes

| Method | Mean ΔE 2000 | 95th percentile | Photos made worse than no change |
|---|---|---|---|
| no change | 4.51 | 7.13 | 0% |
| Reinhard | 3.71 | 7.92 | 38% |
| plain OT | 0.62 | 1.53 | 5% |
| lookmatch | 1.14 | 2.56 | 7% |

Mean ΔE 2000 per look:

| Look | no change | Reinhard | plain OT | lookmatch |
|---|---|---|---|---|
| warm_cool_test | 3.81 | 6.37 | 0.66 | 0.80 |
| teal_orange | 5.86 | 8.06 | 0.89 | 1.22 |
| faded_film | 3.84 | 1.82 | 0.25 | 1.09 |
| cool_moody | 6.44 | 5.69 | 0.70 | 1.04 |
| golden_hour | 9.04 | 4.42 | 0.29 | 1.02 |
| bleach_bypass | 5.20 | 1.75 | 1.07 | 2.42 |
| green_to_teal | 0.68 | 1.04 | 0.57 | 0.67 |
| channel_mix | 1.18 | 0.56 | 0.54 | 0.88 |
