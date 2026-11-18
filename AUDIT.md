# Input and model audit

All four supplied case files were recursively inventoried, including every object
and array element. The reproducible inventory is written to
`.audit/input-inventory.json` by `python audit_models.py`. No official reference
outcomes are supplied. No observations after the checkpoint occur in target history.

| Field | Contents and treatment |
|---|---|
| schema, id | Protocol identity; ids never select predictions. |
| game.name, game.twitch_id | Identity metadata; not a table of answers. |
| day_start, checkpoint | UTC launch origin and observation cutoff; first-hour checkpoint. |
| levels | Exact five levels validated. |
| known | One first-hour print, viewers, channels, reads, from/until. Viewers anchor every forecast; channels inform descriptors. |
| forecast | Exactly hours 2–24, with from/until; no future observations. |
| history | 167, 330, 271, 240 rows respectively. Last observations are hour 1, not hour 2. |
| history_hourly | Already aggregated hourly history; preferred over minute history so analog and target features share units. |
| streams | Null in all practice cases. Final can supply login/viewers/language/started_at. No historical stream-level calibration exists, so these do not receive invented regression coefficients. |
| categories_hourly | Null in all practice cases. Final category totals lack matched analog labels, so no unvalidated causal market adjustment is applied. |
| comparables | 38 per practice case: 37 launches plus target pre-release history. All four practice launches are excluded from every practice comparable pool. |
| comparables[].hourly | from/viewers/channels/reads; covers pre-launch and post-launch days. Release-day outcomes train analog models only, never the target's future. |
| comparables[].unlock/platforms | Rolling versus simultaneous release, early access, weak analogy and console/PC metadata. |
| comparables[].name/source | Identity/provenance. No dedicated genre column exists. |
| notes | Target release/platform information and provenance. No fabricated genre labels are inferred. |

`reads` reports observation count, not another viewer observation. Future comparable
peaks cannot be used as a target-matching feature: its peak is unknown at forecast
time. Full comparable curves already contribute their peak magnitude and timing as
training responses; only pre-checkpoint target values select weights.

The upgraded model blends the original weighted log-ratio distribution with a
centered ridge regression on launch scale, conditioned by pre-release momentum,
console family, rolling unlock and early access. Residual quantiles use adjacent-hour
pooling and weighted empirical interpolation. For every outer historical holdout,
both its regression and every calibration residual fit exclude that launch.
This prevents the common residual-calibration leak. Hyperparameters were selected
using these historical folds: reported numbers are development cross-validation,
not an independent final test or a guarantee of GTA VI accuracy. Richer regressions
using channels and multiple momentum measures were tested, but did not improve the
console validation group enough to justify their complexity.

The observed server loss 0.209214, coverage 0.934783 and run_ms 910 belong to
commit a4114c3, not this version. The server reports wall_ms 1819 for two executions;
the rules aggregate time across all four cases per execution. Neither datum proves
an 800 ms Python interpreter cold start. Local Node measurements include startup,
JSON parsing and all fitting; only a future server grade can establish its run_ms.

The final case adds four analog launches unavailable in practice, and has minute
history and possibly stream/category context. The program reads its actual supplied
comparables rather than shipping frozen answers. Determinism tests repeat every
practice case 12 times, check exact bytes, and validate positive ordered quantiles.
