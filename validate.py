"""Reproducible validation on official input and held-out analog launch curves.

Official p00--p03 outcome labels are not included in the practice kit. The
cross-validation scores below therefore describe held-out comparables, not the
official practice grade. No network or third-party packages are used.
"""

import hashlib
import importlib.util
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("entry", ROOT / "main.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)
LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)


def metric(actual, output):
    loss, absolute, covered = [], [], []
    for row in output["hours"]:
        if row["hour"] not in actual:
            continue
        y = max(1.0, actual[row["hour"]])
        for level, quantile in zip(LEVELS, row["q"]):
            residual = math.log(y) - math.log(quantile)
            loss.append(2 * max(level * residual, (level - 1) * residual))
        absolute.append(abs(math.log(y) - math.log(row["q"][2])))
        covered.append(row["q"][0] <= y <= row["q"][-1])
    return loss, absolute, covered


def baseline(first):
    return {"hours": [{"hour": hour, "q": [max(0.01, math.floor(
        max(1, first) * math.exp(z * .15 * math.sqrt(hour - 1)) * 100 + .5) / 100)
        for z in (-1.645, -.674, 0, .674, 1.645)]} for hour in range(2, 25)]}


def validate_output(data):
    assert set(data) == {"hours"}
    assert len(data["hours"]) == 23
    assert sorted(row["hour"] for row in data["hours"]) == list(range(2, 25))
    for row in data["hours"]:
        assert set(row) == {"hour", "q"}
        assert len(row["q"]) == 5 and row["q"] == sorted(row["q"])
        assert all(isinstance(v, (int, float)) and math.isfinite(v)
                   and 0 < v <= 1e9 for v in row["q"])


def main():
    kit = ROOT / "gta6-twitch-ccu-forecast-01-kit"
    cases = [json.loads(p.read_text(encoding="utf-8"))
             for p in sorted((kit / "input").glob("*.in"))]
    assert len(cases) == 4
    hashes, timings = {}, []
    with tempfile.TemporaryDirectory(dir=ROOT) as temp:
        temp = Path(temp)
        for case in cases:
            source = temp / case["id"]
            source.mkdir()
            (source / (case["id"] + ".in")).write_text(json.dumps(case), encoding="utf-8")
            outputs = []
            for run in range(2):
                destination = source / str(run)
                destination.mkdir()
                env = dict(os.environ, MAKEFUN_INPUT_DIR=str(source),
                           MAKEFUN_OUTPUT_DIR=str(destination), PYTHONHASHSEED="0")
                start = time.perf_counter()
                subprocess.run([sys.executable, "-P", "-s", str(ROOT / "main.py")],
                               env=env, check=True, timeout=8)
                timings.append((time.perf_counter() - start) * 1000)
                content = (destination / (case["id"] + ".out")).read_bytes()
                assert len(content) <= 65536
                validate_output(json.loads(content))
                outputs.append(content)
            assert outputs[0] == outputs[1], case["id"]
            hashes[case["id"]] = hashlib.sha256(outputs[0]).hexdigest()

    analogs = [item for item in cases[0]["comparables"]
               if "target-history" not in item.get("unlock", "").lower()]
    totals = {key: [[], [], []] for key in ("all_analogs", "console_only")}
    bases = {key: [[], [], []] for key in totals}
    details = []
    for item in analogs:
        day = item["day_start"][:10]
        day_rows = {int(row["from"][11:13]) + 1: row for row in item["hourly"]
                    if row["from"][:10] == day and row.get("viewers") is not None}
        if 1 not in day_rows or len(day_rows) < 13:
            continue
        pseudo = {"day_start": item["day_start"],
                  "known": [dict(day_rows[1], hour=1)],
                  "history": [dict(row, at=row["from"]) for row in item["hourly"]
                              if row["from"][:10] < day],
                  "comparables": [other for other in analogs if other is not item],
                  "forecast": [{"hour": hour} for hour in range(2, 25)]}
        actual = {hour: row["viewers"] for hour, row in day_rows.items()}
        predicted = entry.forecast_case(pseudo)
        validate_output(predicted)
        scores = metric(actual, predicted)
        flat_scores = metric(actual, baseline(day_rows[1]["viewers"]))
        platform = item.get("platforms", "").lower()
        console_only = "pc" not in platform
        groups = ["all_analogs"] + (["console_only"] if console_only else [])
        for group in groups:
            for index in range(3):
                totals[group][index].extend(scores[index])
                bases[group][index].extend(flat_scores[index])
        details.append({"name": item["name"], "console_only": console_only,
                        "loss": statistics.mean(scores[0]),
                        "baseline_loss": statistics.mean(flat_scores[0])})
    report = {"official_practice_score": None,
              "official_practice_score_reason": "Reference outcomes stay on the make.fun server.",
              "practice_outputs_valid": 4, "deterministic": True, "sha256": hashes,
              "runtime": sys.version.split()[0], "process_ms_mean": statistics.mean(timings),
              "process_ms_max": max(timings), "analog_cross_validation": {},
              "launches": details}
    for group in totals:
        values, errors, coverage = totals[group]
        if values:
            report["analog_cross_validation"][group] = {
                "loss": statistics.mean(values),
                "baseline_loss": statistics.mean(bases[group][0]),
                "typical_miss_pct": 100 * math.expm1(statistics.mean(errors)),
                "coverage_90": statistics.mean(coverage), "hours": len(errors)}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
