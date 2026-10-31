# Benchmark results

How close each method gets to a known look, on photos it never saw as references. Score: mean ΔE 2000 against the right answer (below about 1 is invisible; lower is better). Method: [bench/benchmark.py](benchmark.py).

## Setup

- date: 2026-10-31
- lookmatch version: 0.1.0.dev0
- photos: 4
- photo size: 800 px long side
- looks: warm_cool_test, teal_orange, faded_film, cool_moody, golden_hour, bleach_bypass, green_to_teal, channel_mix
- folds: 3
- lookmatch transport strength: 0.5

## Different scenes

| Method | Mean ΔE 2000 | 95th percentile | Photos made worse than no change |
|---|---|---|---|
| no change | 4.67 | 7.01 | 0% |
| Reinhard | 13.60 | 18.76 | 90% |
| plain OT | 15.13 | 24.32 | 92% |
| lookmatch | 14.23 | 23.27 | 93% |

Mean ΔE 2000 per look:

| Look | no change | Reinhard | plain OT | lookmatch |
|---|---|---|---|---|
| warm_cool_test | 3.23 | 13.58 | 16.28 | 15.15 |
| teal_orange | 5.95 | 16.23 | 15.97 | 14.83 |
| faded_film | 4.33 | 12.32 | 13.47 | 12.68 |
| cool_moody | 6.60 | 14.34 | 15.18 | 14.49 |
| golden_hour | 8.91 | 13.34 | 15.39 | 14.30 |
| bleach_bypass | 6.74 | 12.10 | 14.13 | 13.56 |
| green_to_teal | 0.06 | 13.61 | 15.53 | 14.63 |
| channel_mix | 1.56 | 13.24 | 15.06 | 14.19 |

## Same scenes

| Method | Mean ΔE 2000 | 95th percentile | Photos made worse than no change |
|---|---|---|---|
| no change | 4.67 | 7.01 | 0% |
| Reinhard | 2.91 | 5.69 | 31% |
| plain OT | 0.42 | 1.15 | 10% |
| lookmatch | 1.26 | 2.50 | 12% |

Mean ΔE 2000 per look:

| Look | no change | Reinhard | plain OT | lookmatch |
|---|---|---|---|---|
| warm_cool_test | 3.23 | 4.76 | 0.33 | 1.31 |
| teal_orange | 5.95 | 5.99 | 0.70 | 1.78 |
| faded_film | 4.33 | 1.41 | 0.21 | 1.24 |
| cool_moody | 6.60 | 4.73 | 0.54 | 1.30 |
| golden_hour | 8.91 | 3.41 | 0.30 | 0.87 |
| bleach_bypass | 6.74 | 2.21 | 0.92 | 2.77 |
| green_to_teal | 0.06 | 0.13 | 0.08 | 0.09 |
| channel_mix | 1.56 | 0.64 | 0.31 | 0.72 |
