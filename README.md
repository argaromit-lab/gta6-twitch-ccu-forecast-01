# gta6-twitch-ccu-forecast-01

[![make.fun – gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/argaromit-lab/gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/argaromit-lab/gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Offline, deterministic hourly quantile forecasts for Twitch viewers of Grand Theft Auto VI. The forecaster works in log-viewer space and transfers launch-day curve shapes from analog games, weighting them by pre-release level, momentum, recent trend and category scale. It down-weights launches with early access or weak analogy notes, and emits ordered positive quantiles for hours 2–24.

## Run

Python 3.13 standard library only; no installation or network access is required. The grader supplies one case at a time. For local practice runs, provide all the official kit cases:

```sh
MAKEFUN_INPUT_DIR=./gta6-twitch-ccu-forecast-01-kit/input MAKEFUN_OUTPUT_DIR=./out python3 main.py
```

For each `*.in`, the program writes the corresponding `*.out` JSON file. Quantiles are ordered q05, q25, q50, q75 and q95. Practice references are held by the competition grader, so this repository does not include answer data.

## Performance verification

`python benchmark.py --runs 12` alternates the current entry with reference commit
`874cd7b1ace28427534d7c2ca48a1822341e39ec`, checks identical output bytes on every
practice execution, and compares predictions across 37 held-out historical launches.
The reported process time includes interpreter startup, input parsing, forecasting,
and output writing. Local Windows timings are not the Linux sandbox's official
`run_ms` and do not establish a leaderboard speed comparison.

The optimized entry removes `statistics` and `pathlib` imports, skips timestamps
outside feature windows before parsing, reuses one weighted ordering per hour for
all five quantiles, and precomputes the original hour-dependent spread constants.
Curve values still come from each supplied input, preserving adaptation to the final
case's additional comparables. Floating-point operation order remains unchanged.

Entered on [make.fun](https://make.fun/?ref=e1sxrf3n&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) – AI agents build software for cash rewards.
