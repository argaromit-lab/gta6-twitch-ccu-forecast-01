"""Deterministic, log-space launch-shape forecasting for Twitch category viewers."""

import json
import math
import os
from datetime import datetime, timedelta

LEVELS = (0.05, 0.25, 0.50, 0.75, 0.95)
LOG_CAP = math.log(1_000_000_000)
LOG_FLOOR = math.log(0.01)
Z_VALUES = (-1.645, -0.674, 0, 0.674, 1.645)
# Preserve the reference's operation order for bit-identical floating-point results.
HOUR_PARAMETERS = tuple((0.78 if hour <= 6 else 0.72,
                         tuple(z * (0.08 * math.sqrt(hour - 1)) for z in Z_VALUES))
                        for hour in range(2, 25))


def log_viewers(value):
    return math.log(max(1.0, float(value or 0)))


def hour_number(instant, day_start):
    point = datetime.fromisoformat(instant.replace("Z", "+00:00"))
    return (point - day_start).total_seconds() / 3600.0


def median(values, fallback=0.0):
    if not values:
        return fallback
    values.sort()
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2


def robust_slope(points):
    slopes = []
    for left in range(len(points)):
        t0, y0 = points[left]
        for right in range(left + 1, len(points)):
            t1, y1 = points[right]
            if t1 > t0:
                slopes.append((y1 - y0) / (t1 - t0))
    return median(slopes)


def launch_features(rows, day_start, first_viewers, first_channels):
    first_log = log_viewers(first_viewers)
    pre = []
    # Only the final 24 hours affect the normal path. The older median is a
    # fallback, so defer its timestamp parsing and logarithms until needed.
    lower = (day_start - timedelta(hours=24)).isoformat().replace("+00:00", "Z")
    upper = day_start.isoformat().replace("+00:00", "Z")
    for row in rows:
        instant = row.get("from") or row.get("at", "")
        if not lower <= instant < upper:
            continue
        value = row.get("viewers")
        if value is None or value <= 0:
            continue
        offset = hour_number(instant, day_start)
        if -24 * 14 <= offset < 0:
            pre.append((offset, log_viewers(value), row.get("channels")))

    recent = [y for t, y, _ in pre if t >= -24]
    previous = []
    if not recent:
        older = (day_start - timedelta(hours=168)).isoformat().replace("+00:00", "Z")
        for row in rows:
            instant = row.get("from") or row.get("at", "")
            value = row.get("viewers")
            if older <= instant < lower and value is not None and value > 0:
                previous.append(log_viewers(value))
    trend_points = [(t, y) for t, y, _ in pre if t >= -24]
    pre_level = median(recent, median(previous, first_log))
    trend = robust_slope(trend_points) if len(trend_points) >= 2 else 0.0
    pre_channels = [math.log(max(1.0, float(c))) for t, _, c in pre if t >= -24 and c]

    return {
        "first": first_log,
        "momentum": first_log - pre_level,
        "trend": max(-0.12, min(0.12, trend * 24.0)),
        "channels": math.log(max(1.0, float(first_channels or 1))),
        "channel_change": math.log(max(1.0, float(first_channels or 1))) - median(pre_channels),
    }


def metadata_flags(item):
    text = (str(item.get("unlock") or "") + " " + str(item.get("platforms") or "")).lower()
    if "midnight local" in text or "rolling" in text:
        rollout = 1.0
    elif "simultaneous" in text or "global unlock" in text:
        rollout = 0.0
    else:
        rollout = 0.5
    early = 1.0 if "early access" in text or "early-access" in text else 0.0
    weak = 1.0 if "tier: weak" in text or "weak analogue" in text else 0.0
    return rollout, early, weak


def comparable_curve(item):
    if "target-history" in (item.get("unlock") or "").lower():
        return None
    day_start = datetime.fromisoformat(item["day_start"])
    rows = item.get("hourly") or []
    curve = {}
    launch_channels = None
    lower = (day_start - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    upper = (day_start + timedelta(hours=25)).isoformat().replace("+00:00", "Z")
    for row in rows:
        if not lower <= row["from"] < upper:
            continue
        offset = hour_number(row["from"], day_start)
        hour = int(round(offset))
        viewers = row.get("viewers")
        if 0 <= hour < 24 and viewers is not None:
            curve[hour] = log_viewers(viewers)
            if hour == 0:
                launch_channels = row.get("channels")
    if 0 not in curve:
        return None
    first = curve[0]
    normalized = {hour: value - first for hour, value in curve.items()}
    flags = metadata_flags(item)
    return {"curve": normalized, "features": launch_features(rows, day_start,
            math.exp(first), launch_channels),
            "rollout": flags[0], "early": flags[1], "weak": flags[2]}


def similarity(target, donor):
    a, b = target["features"], donor["features"]
    distance = ((a["first"] - b["first"]) / 1.2) ** 2
    distance += ((a["momentum"] - b["momentum"]) / 2.0) ** 2
    distance += ((a["trend"] - b["trend"]) / 0.8) ** 2
    distance += ((a["channel_change"] - b["channel_change"]) / 1.8) ** 2
    weight = math.exp(-0.5 * min(distance, 40.0))
    if target["rollout"] != donor["rollout"]:
        weight *= 0.42
    if donor["early"]:
        weight *= 0.38
    if donor["weak"]:
        weight *= 0.35
    return weight


def weighted_quantiles(pairs):
    pairs = sorted((value, weight) for value, weight in pairs if weight > 1e-12)
    if not pairs:
        return (0.0,) * 5
    total = sum(weight for _, weight in pairs)
    # Interpolate at weighted mid-ranks instead of returning a staircase: with
    # a modest analog pool this keeps adjacent quantiles ordered and calibrated.
    points = []
    cumulative = 0.0
    for value, weight in pairs:
        points.append(((cumulative + 0.5 * weight) / total, value))
        cumulative += weight
    result = []
    for probability in LEVELS:
        if probability <= points[0][0]:
            result.append(points[0][1])
        elif probability >= points[-1][0]:
            result.append(points[-1][1])
        else:
            for (left_p, left_v), (right_p, right_v) in zip(points, points[1:]):
                if probability <= right_p:
                    fraction = (probability - left_p) / max(1e-12, right_p - left_p)
                    result.append(left_v + fraction * (right_v - left_v))
                    break
    return result


def target_curve(case):
    known = next((row for row in case.get("known", []) if row.get("hour") == 1), None)
    if known is None:
        raise ValueError("missing hour-1 print")
    flags = metadata_flags({"unlock": "midnight local rolling", "platforms": "PS5 Xbox"})
    return {
        "features": launch_features(case.get("history_hourly") or case.get("history", []),
                                    datetime.fromisoformat(case["day_start"]),
                                    known["viewers"], known.get("channels")),
        "rollout": flags[0], "early": 0.0, "weak": 0.0,
        "first": log_viewers(known["viewers"]),
    }


def forecast_case(case):
    if tuple(case.get("levels", LEVELS)) != LEVELS:
        raise ValueError("unsupported quantile levels")
    target = target_curve(case)
    donors = []
    for item in case.get("comparables") or []:
        donor = comparable_curve(item)
        if donor is not None:
            donor["weight"] = similarity(target, donor)
            donors.append(donor)

    forecasts = []
    requested = case.get("forecast", [])
    if sorted(row["hour"] for row in requested) != list(range(2, 25)):
        raise ValueError("expected exactly hours 2 through 24")
    for row in sorted(requested, key=lambda item: item["hour"]):
        hour = int(row["hour"])
        offset = hour - 1
        pairs = [(donor["curve"][offset], donor["weight"])
                 for donor in donors if offset in donor["curve"]]
        curve_quantiles = weighted_quantiles(pairs)
        center = curve_quantiles[2]
        # Robustly temper cross-launch dispersion: extreme launch regimes inform the
        # tails, while the central forecast stays close to the matched analog median.
        spread, floor_deviations = HOUR_PARAMETERS[hour - 2]
        # Keep uncertainty even when few historical curves carry most of the weight.
        logs = []
        for curve_quantile, z, floor_deviation in zip(curve_quantiles, Z_VALUES, floor_deviations):
            deviation = spread * (curve_quantile - center)
            if z:
                deviation = math.copysign(math.hypot(deviation, floor_deviation), z)
            logs.append(target["first"] + center + deviation)
        quantiles = []
        previous = 0.0
        for value in logs:
            value = max(LOG_FLOOR, min(LOG_CAP, value))
            quantile = math.exp(value)
            quantile = max(previous, min(1_000_000_000.0, quantile))
            quantiles.append(round(quantile, 4))
            previous = quantile
        forecasts.append({"hour": hour, "q": quantiles})
    return {"hours": forecasts}


def main():
    input_dir = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
    output_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(output_dir, exist_ok=True)
    for name in sorted(os.listdir(input_dir)):
        if not name.endswith(".in"):
            continue
        with open(os.path.join(input_dir, name), encoding="utf-8") as stream:
            case = json.load(stream)
        output = forecast_case(case)
        with open(os.path.join(output_dir, name[:-3] + ".out"), "w", encoding="utf-8") as stream:
            stream.write(json.dumps(output, separators=(",", ":"), allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
