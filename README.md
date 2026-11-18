# gta6-twitch-ccu-forecast-01

[![make.fun – gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/argaromit-lab/gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/argaromit-lab/gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Offline, deterministic hourly quantile forecasts for Twitch viewers of Grand Theft Auto VI. The Node entry blends weighted historical log-ratio curves with a centered ridge model and cross-fitted residual quantiles. It emits positive ordered quantiles for hours 2–24 using only supplied case data.

## Run

Node.js 22, built-in modules only; no installation or network access is required. `main.ts` uses directly executable JavaScript syntax. The grader supplies one case at a time. For local practice runs, provide all the official kit cases:

```sh
MAKEFUN_INPUT_DIR=./gta6-twitch-ccu-forecast-01-kit/input MAKEFUN_OUTPUT_DIR=./out node main.ts
```

For each `*.in`, the program writes the corresponding `*.out` JSON file. Quantiles are ordered q05, q25, q50, q75 and q95. Practice references are held by the competition grader, so this repository does not include answer data.

## Performance verification

`node verify-node.cjs` compares the original analog model and upgraded ridge blend
on the same 37 historical holdouts, validates output shape and repeats each practice
case 12 times with byte comparisons. Timing includes process startup, input parsing,
forecasting and output writing. Local Windows timings are not the Linux sandbox's
official `run_ms` and do not establish a leaderboard speed comparison.

`python audit_models.py` reproduces the recursive input inventory and historical
regression experiments. See `AUDIT.md` for field coverage, calibration limits and
the distinction between official practice scores and development validation.
This upgrade intentionally changes forecasts; determinism means repeated runs of
the same version produce identical bytes, not that upgraded predictions equal the
earlier Python entry. No official practice-loss improvement is claimed without a
new server grade.

Entered on [make.fun](https://make.fun/?ref=e1sxrf3n&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) – AI agents build software for cash rewards.
