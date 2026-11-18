"""Input inventory and strictly held-out launch-model experiments (stdlib only)."""

import collections
import datetime as dt
import importlib.util
import json
import math
import statistics as stats
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "gta6-twitch-ccu-forecast-01-kit" / "input"
TAUS = (.05, .25, .5, .75, .95)
Z = (-1.645, -.674, 0, .674, 1.645)


def inventory():
    result = {}
    for path in sorted(INPUT.glob("*.in")):
        case = json.loads(path.read_bytes())
        fields = {}

        def visit(value, name):
            kinds = fields.setdefault(name, collections.Counter())
            kinds[type(value).__name__] += 1
            if isinstance(value, dict):
                for key, child in value.items():
                    visit(child, name + "." + key)
            elif isinstance(value, list):
                for child in value:
                    visit(child, name + "[]")

        visit(case, "case")
        result[path.stem] = {
            "fields": fields, "bytes": path.stat().st_size,
            "history_range": [case["history"][0]["at"], case["history"][-1]["at"]],
            "history_rows": len(case["history"]), "known": case["known"],
            "post_checkpoint_history": sum(r["at"] >= case["checkpoint"] for r in case["history"]),
            "comparables": [{"name": c["name"], "rows": len(c["hourly"]),
                              "first": c["hourly"][0]["from"], "last": c["hourly"][-1]["from"],
                              "unlock": c["unlock"], "platforms": c["platforms"]}
                             for c in case["comparables"]],
        }
    return result


def log(v):
    return math.log(max(1, v or 0))


def med(v, default=0):
    return stats.median(v) if v else default


def descriptor(item):
    day = dt.datetime.fromisoformat(item["day_start"])
    rows = [(int((dt.datetime.fromisoformat(r["from"]) - day).total_seconds() // 3600), r)
            for r in item["hourly"]]
    dayrows = {h: r for h, r in rows if 0 <= h < 24}
    if 0 not in dayrows or any(h not in dayrows for h in range(24)):
        return None
    if "target-history" in item.get("unlock", "").lower():
        return None
    p = log(dayrows[0]["viewers"])
    channels = log(dayrows[0].get("channels"))
    pre = [(h, r) for h, r in rows if -168 <= h < 0]
    last = [log(r["viewers"]) for h, r in pre if h >= -24 and r["viewers"] > 0]
    near = [log(r["viewers"]) for h, r in pre if h >= -3 and r["viewers"] > 0]
    peak = max((log(r["viewers"]) for h, r in pre if h >= -24), default=p)
    cpre = [log(r["channels"]) for h, r in pre if h >= -24 and r.get("channels")]
    note = item.get("unlock", "").lower()
    platform = item.get("platforms", "").lower()
    console = "pc" not in platform
    early = "early access" in note or "early-access" in note
    rollout = 1 if "rolling" in note or "midnight local" in note else (
        0 if "simultaneous" in note or "global unlock" in note else .5)
    return {"name": item["name"], "x": [p, channels, p - med(last, p),
            p - med(near, p), p - peak, channels - med(cpre, channels)],
            "y": [log(dayrows[h]["viewers"]) - p for h in range(1, 24)],
            "console": console, "early": early, "rollout": rollout, "item": item}


def solve(a, b):
    n = len(a)
    width = len(b[0])
    m = [a[i][:] + b[i][:] for i in range(n)]
    for j in range(n):
        pivot = max(range(j, n), key=lambda i: abs(m[i][j]))
        m[j], m[pivot] = m[pivot], m[j]
        z = m[j][j]
        if abs(z) < 1e-12:
            raise ValueError("singular regression")
        m[j] = [v / z for v in m[j]]
        for i in range(n):
            if i != j:
                z = m[i][j]
                for k in range(j, n + width):
                    m[i][k] -= z * m[j][k]
    return [r[n:] for r in m]


def weights(target, donors, cfg):
    out = []
    for d in donors:
        distance = sum(((target["x"][j] - d["x"][j]) / bandwidth) ** 2
                       for j, bandwidth in cfg["kernel"])
        w = math.exp(-.5 * min(distance, 40))
        if target["console"] != d["console"]:
            w *= cfg["family"]
        if target["rollout"] != d["rollout"]:
            w *= .55
        if target["early"] != d["early"]:
            w *= .5
        out.append(w)
    return out


def center(target, donors, cfg):
    indices = cfg["features"]
    w = weights(target, donors, cfg)
    sw = sum(w)
    w = [v * len(w) / sw for v in w]
    scales = (2, 2, 2, 1, 1, 2)
    x = [[1] + [(d["x"][j] - target["x"][j]) / scales[j] for j in indices] for d in donors]
    k = len(indices) + 1
    a = [[sum(v * xx[i] * xx[j] for v, xx in zip(w, x))
          + (cfg["ridge"] if i == j and i else 0) for j in range(k)] for i in range(k)]
    b = [[sum(v * xx[i] * d["y"][h] for v, xx, d in zip(w, x, donors))
          for h in range(23)] for i in range(k)]
    beta = solve(a, b)
    # Avoid aggressive extrapolation far beyond the analog scale.
    return [max(-7, min(10, v)) for v in beta[0]]


def wq(pairs, tau):
    pairs = sorted((v, w) for v, w in pairs if w > 1e-12)
    sw = sum(w for v, w in pairs)
    pts, accum = [], 0
    for v, w in pairs:
        pts.append(((accum + w * .5) / sw, v))
        accum += w
    if tau <= pts[0][0]:
        return pts[0][1]
    if tau >= pts[-1][0]:
        return pts[-1][1]
    for (p0, v0), (p1, v1) in zip(pts, pts[1:]):
        if tau <= p1:
            return v0 + (tau - p0) / max(1e-12, p1 - p0) * (v1 - v0)


def cv_predictions(items, cfg):
    predictions = []
    for outer, target in enumerate(items):
        donors = [d for i, d in enumerate(items) if i != outer]
        mu = center(target, donors, cfg)
        # Every residual model excludes the OUTER target as well as its own donor.
        # Thus neither the regression nor its spread calibration sees held-out y.
        residuals = []
        for j, d in enumerate(donors):
            fit = center(d, [e for k, e in enumerate(donors) if j != k], cfg)
            residuals.append([d["y"][h] - fit[h] for h in range(23)])
        ws = weights(target, donors, cfg)
        spread_ws = [math.sqrt(w) for w in ws]
        qrows = []
        for h in range(23):
            # Adjacent hours share calibration, without copying whole outcomes.
            pool = [(errors[k], w / (1 + abs(k - h)))
                    for errors, w in zip(residuals, spread_ws)
                    for k in range(max(0, h - 1), min(23, h + 2))]
            qrows.append([mu[h] + wq(pool, q) for q in TAUS])
        predictions.append(qrows)
    return predictions


def score(items, predictions, console=None):
    costs, covers, errors = [], [], []
    for item, forecast in zip(items, predictions):
        if console is not None and item["console"] != console:
            continue
        for y, qs in zip(item["y"], forecast):
            costs.extend(2 * max(q * (y - p), (q - 1) * (y - p)) for q, p in zip(TAUS, qs))
            covers.append(qs[0] <= y <= qs[4])
            errors.append(abs(y - qs[2]))
    return {"loss": stats.mean(costs), "coverage_90": stats.mean(covers),
            "median_log_error": stats.mean(errors), "hours": len(errors)}


def main():
    (ROOT / ".audit" / "input-inventory.json").write_text(json.dumps(inventory(), indent=2), encoding="utf-8")
    case = json.loads((INPUT / "p00.in").read_bytes())
    items = [d for item in case["comparables"] if (d := descriptor(item))]
    baseline_ns = {"__name__": "baseline"}
    exec(compile(subprocess.check_output(["git", "show", "a4114c3:main.py"], cwd=ROOT),
                 "baseline.py", "exec"), baseline_ns)
    baseline = []
    for t in items:
        item = t["item"]
        known = next(r for r in item["hourly"] if r["from"] == item["day_start"])
        pseudo = {"day_start": item["day_start"], "known": [dict(known, hour=1)],
                  "forecast": [{"hour": h} for h in range(2, 25)],
                  "history": [dict(r, at=r["from"]) for r in item["hourly"] if r["from"] < item["day_start"]],
                  "comparables": [d["item"] for d in items if d is not t]}
        out = baseline_ns["forecast_case"](pseudo)
        baseline.append([[math.log(q) - t["x"][0] for q in r["q"]] for r in out["hours"]])
    print("BASELINE", score(items, baseline), "CONSOLE", score(items, baseline, True), flush=True)
    configs = []
    for features in [(0,), (0, 1), (0, 2), (0, 1, 3), (0, 1, 2), (0, 1, 2, 3)]:
        for ridge in [2, 10]:
            configs.append({"features": features, "kernel": [(0, 2), (2, 2)],
                            "ridge": ridge, "family": .4})
    results = []
    for cfg in configs:
        pred = cv_predictions(items, cfg)
        for blend in [.4, .7, 1.0]:
            mixed = [[[a * (1 - blend) + b * blend for a, b in zip(q0, q1)]
                      for q0, q1 in zip(p0, p1)] for p0, p1 in zip(baseline, pred)]
            full, console = score(items, mixed), score(items, mixed, True)
            row = {"config": cfg, "blend": blend, "all": full, "console": console}
            results.append(row)
            print(json.dumps(row), flush=True)
    (ROOT / ".audit" / "model-experiments.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
