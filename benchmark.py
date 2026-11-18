"""Compare committed reference and current entry, including exact output bytes."""

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REFERENCE = "874cd7b1ace28427534d7c2ca48a1822341e39ec"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=12)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    source = subprocess.check_output(["git", "show", REFERENCE + ":main.py"], cwd=ROOT)
    reference_namespace = {"__name__": "reference"}
    exec(compile(source, "reference/main.py", "exec"), reference_namespace)
    optimized_namespace = {"__name__": "optimized"}
    exec(compile((ROOT / "main.py").read_bytes(), "optimized/main.py", "exec"), optimized_namespace)
    inputs = ROOT / "gta6-twitch-ccu-forecast-01-kit" / "input"
    report = {"reference_commit": REFERENCE, "python": sys.version,
              "platform": sys.platform, "cases": {}}
    analogs = json.loads((inputs / "p00.in").read_bytes())["comparables"]
    checked = 0
    for item in analogs:
        day = item["day_start"][:10]
        first = next((row for row in item["hourly"]
                      if row["from"] == item["day_start"]), None)
        if first is None or "target-history" in item.get("unlock", "").lower():
            continue
        case = {"day_start": item["day_start"], "known": [dict(first, hour=1)],
                "history": [dict(row, at=row["from"]) for row in item["hourly"]
                            if row["from"][:10] < day],
                "comparables": [other for other in analogs if other is not item],
                "forecast": [{"hour": hour} for hour in range(2, 25)]}
        assert (reference_namespace["forecast_case"](case) ==
                optimized_namespace["forecast_case"](case)), item["name"]
        checked += 1
    report["held_out_analog_predictions_identical"] = checked
    with tempfile.TemporaryDirectory(dir=ROOT / ".audit") as scratch:
        scratch = Path(scratch)
        reference = scratch / "reference.py"
        reference.write_bytes(source)
        for path in sorted(inputs.glob("*.in")):
            case_dir = scratch / path.stem
            case_dir.mkdir()
            (case_dir / path.name).write_bytes(path.read_bytes())
            out = case_dir / "out"
            out.mkdir()
            env = dict(os.environ, MAKEFUN_INPUT_DIR=str(case_dir),
                       MAKEFUN_OUTPUT_DIR=str(out), PYTHONHASHSEED="0")
            timings = {"reference": [], "optimized": []}
            expected = None
            # Alternate execution order to reduce cache and machine-load bias.
            for iteration in range(args.runs + 1):
                modes = ("reference", "optimized") if iteration % 2 == 0 else ("optimized", "reference")
                for mode in modes:
                    entry = reference if mode == "reference" else ROOT / "main.py"
                    start = time.perf_counter_ns()
                    # Blocking wait uses the OS process handle directly. A timeout
                    # would introduce exponential polling sleeps into this timing.
                    subprocess.run([sys.executable, "-P", "-s", str(entry)], env=env,
                                   cwd=ROOT, check=True)
                    duration = (time.perf_counter_ns() - start) / 1_000_000
                    content = (out / (path.stem + ".out")).read_bytes()
                    if expected is None:
                        expected = content
                    assert content == expected, (path.stem, mode, iteration)
                    if iteration:
                        timings[mode].append(duration)
            report["cases"][path.stem] = {
                "byte_identical": True,
                "sha256": hashlib.sha256(expected).hexdigest(),
                **{mode: {"median_ms": statistics.median(values),
                          "min_ms": min(values), "max_ms": max(values)}
                   for mode, values in timings.items()}}
        for mode in ("reference", "optimized"):
            report[mode + "_median_ms"] = statistics.mean(
                item[mode]["median_ms"] for item in report["cases"].values())
        report["speedup"] = report["reference_median_ms"] / report["optimized_median_ms"]
    rendered = json.dumps(report, indent=2)
    if args.report:
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
