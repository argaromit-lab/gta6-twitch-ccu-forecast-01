// Offline Node 22 entry. Plain JavaScript syntax avoids a transpilation dependency.
// All fitting uses supplied historical comparables, never case ids or future target rows.
const fs = require('node:fs');
const path = require('node:path');
const LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95];
const Z = [-1.645, -0.674, 0, 0.674, 1.645];
const HOUR = 3600000;
const logv = v => Math.log(Math.max(1, Number(v || 0)));
const clip = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
const PARAMS = Object.freeze({ ridge: 10, blend: 0.6, family: 0.4, spread: 0.85 });

function median(values, fallback = 0) {
  if (!values.length) return fallback;
  values.sort((a, b) => a - b);
  const j = values.length >> 1;
  return values.length % 2 ? values[j] : (values[j - 1] + values[j]) / 2;
}

function flags(item) {
  const text = `${item.unlock || ''} ${item.platforms || ''}`.toLowerCase();
  return {
    rollout: /midnight local|rolling/.test(text) ? 1 : /simultaneous|global unlock/.test(text) ? 0 : 0.5,
    early: /early access|early-access/.test(text),
    weak: /tier: weak|weak analogue/.test(text),
    console: !/\bpc\b/i.test(item.platforms || ''),
  };
}

function features(rows, start, first, channels) {
  const p = logv(first), ch = logv(channels), pre = [], old = [];
  const recent = [], near = [], cpre = [], slopes = [];
  let peak = -Infinity;
  const lower = new Date(start - 24 * HOUR).toISOString().slice(0, 19) + 'Z';
  const upper = new Date(start).toISOString().slice(0, 19) + 'Z';
  for (const r of rows) {
    const instant = r.from || r.at;
    if (instant < lower || instant >= upper) continue;
    const h = (Date.parse(instant) - start) / HOUR;
    if (h < -168 || h >= 0 || !(r.viewers > 0)) continue;
    const y = logv(r.viewers);
    if (h >= -24) {
      recent.push(y);
      pre.push([h, y]);
      if (h >= -3) near.push(y);
      if (r.channels) cpre.push(logv(r.channels));
      peak = Math.max(peak, y);
    }
  }
  if (!recent.length) {
    const earlier = new Date(start - 168 * HOUR).toISOString().slice(0, 19) + 'Z';
    for (const r of rows) {
      const instant = r.from || r.at;
      if (instant >= earlier && instant < lower && r.viewers > 0) old.push(logv(r.viewers));
    }
  }
  for (let i = 0; i < pre.length; i++) {
    for (let j = i + 1; j < pre.length; j++) {
      if (pre[j][0] > pre[i][0]) slopes.push((pre[j][1] - pre[i][1]) / (pre[j][0] - pre[i][0]));
    }
  }
  const momentum = p - median(recent, median(old, p));
  return {
    first: p, momentum, trend: clip(median(slopes) * 24, -0.12, 0.12),
    channelChange: ch - median(cpre),
    x: [p, ch, momentum, p - median(near, p), p - (Number.isFinite(peak) ? peak : p),
        ch - median(cpre, ch)],
  };
}

function descriptor(item) {
  if (/target-history/.test((item.unlock || '').toLowerCase())) return null;
  const start = Date.parse(item.day_start), rows = item.hourly || [];
  const logs = Array(24).fill(null);
  let channels = null;
  const lower = new Date(start - HOUR).toISOString().slice(0, 19) + 'Z';
  const upper = new Date(start + 25 * HOUR).toISOString().slice(0, 19) + 'Z';
  for (const row of rows) {
    if (row.from < lower || row.from > upper) continue;
    const t = Date.parse(row.from);
    if (t < start - HOUR || t > start + 25 * HOUR) continue;
    const h = Math.round((t - start) / HOUR);
    if (h >= 0 && h < 24 && row.viewers != null) {
      logs[h] = logv(row.viewers);
      if (!h) channels = row.channels;
    }
  }
  if (logs[0] == null) return null;
  const f = features(rows, start, Math.exp(logs[0]), channels);
  return { name: item.name, f, x: f.x, ...flags(item),
    y: logs.slice(1).map(v => v == null ? null : v - logs[0]),
    full: logs.every(v => v != null) };
}

function targetDescriptor(c) {
  const known = (c.known || []).find(r => r.hour === 1);
  if (!known) throw Error('Missing hour 1');
  const f = features(c.history_hourly || c.history || [], Date.parse(c.day_start), known.viewers, known.channels);
  // Practice notes describe the launch platform; GTA VI is explicitly console-only.
  const note = (c.notes || '').toLowerCase();
  const consoleOnly = /console only|console-only|ps5 only|ps5, ps4|on ps4, xbox one/.test(note)
    || !/\bpc\b/.test(note);
  return { f, x: f.x, rollout: 1, early: false, weak: false, console: consoleOnly };
}

function analogWeight(t, d) {
  const a = t.f, b = d.f;
  let dist = ((a.first - b.first) / 1.2) ** 2;
  dist += ((a.momentum - b.momentum) / 2) ** 2;
  dist += ((a.trend - b.trend) / .8) ** 2;
  dist += ((a.channelChange - b.channelChange) / 1.8) ** 2;
  let w = Math.exp(-.5 * Math.min(dist, 40));
  if (t.rollout !== d.rollout) w *= .42;
  if (d.early) w *= .38;
  if (d.weak) w *= .35;
  return w;
}

function quantiles(pairs) {
  pairs = pairs.filter(p => p[1] > 1e-12).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (!pairs.length) return [0, 0, 0, 0, 0];
  let sum = 0;
  for (const p of pairs) sum += p[1];
  let acc = 0;
  const ranks = pairs.map(([value, weight]) => {
    const p = (acc + .5 * weight) / sum;
    acc += weight;
    return [p, value];
  });
  return LEVELS.map(q => {
    if (q <= ranks[0][0]) return ranks[0][1];
    if (q >= ranks[ranks.length - 1][0]) return ranks[ranks.length - 1][1];
    for (let j = 1; j < ranks.length; j++) {
      if (q <= ranks[j][0]) {
        const [p0, v0] = ranks[j - 1], [p1, v1] = ranks[j];
        return v0 + ((q - p0) / Math.max(1e-12, p1 - p0)) * (v1 - v0);
      }
    }
  });
}

function analogForecast(t, donors) {
  const weights = donors.map(d => analogWeight(t, d));
  return Array.from({ length: 23 }, (_, h) => {
    const q = quantiles(donors.flatMap((d, j) => d.y[h] == null ? [] : [[d.y[h], weights[j]]]));
    const center = q[2], spread = h < 5 ? .78 : .72, floor = .08 * Math.sqrt(h + 1);
    return q.map((v, j) => center + (Z[j] ? Math.sign(Z[j]) * Math.hypot(spread * (v - center), Z[j] * floor) : 0));
  });
}

function regressionWeights(t, donors) {
  return donors.map(d => {
    const distance = ((t.x[0] - d.x[0]) / 2) ** 2 + ((t.x[2] - d.x[2]) / 2) ** 2;
    let w = Math.exp(-.5 * Math.min(distance, 40));
    if (t.console !== d.console) w *= PARAMS.family;
    if (t.rollout !== d.rollout) w *= .55;
    if (t.early !== d.early) w *= .5;
    return w;
  });
}

// Closed-form centered ridge with an unpenalized intercept, all 23 responses together.
function regression(t, donors) {
  let w = regressionWeights(t, donors);
  const total = w.reduce((a, b) => a + b, 0), n = donors.length;
  w = w.map(v => v * n / total);
  let s0 = 0, s1 = 0, s2 = PARAMS.ridge;
  const b0 = Array(23).fill(0), b1 = Array(23).fill(0);
  for (let i = 0; i < n; i++) {
    const d = donors[i], v = w[i], x = (d.x[0] - t.x[0]) / 2;
    s0 += v; s1 += v * x; s2 += v * x * x;
    for (let h = 0; h < 23; h++) {
      b0[h] += v * d.y[h];
      b1[h] += v * x * d.y[h];
    }
  }
  const determinant = s0 * s2 - s1 * s1;
  return b0.map((v, h) => clip((v * s2 - s1 * b1[h]) / determinant, -7, 10));
}

function prepare(donors) {
  const complete = donors.filter(d => d.full);
  if (complete.length < 6) return null;
  const residuals = complete.map((d, i) => {
    const fit = regression(d, complete.filter((_, j) => j !== i));
    return d.y.map((y, h) => y - fit[h]);
  });
  return { complete, residuals };
}

function predict(t, donors, prepared = prepare(donors), mode = 'blend') {
  const analog = analogForecast({ ...t, rollout: 1 }, donors);
  if (!prepared || mode === 'analog') return analog;
  const { complete, residuals } = prepared;
  const mu = regression(t, complete);
  const ws = regressionWeights(t, complete).map(Math.sqrt);
  return analog.map((q, h) => {
    const pool = [];
    for (let j = 0; j < residuals.length; j++) {
      for (let k = Math.max(0, h - 1); k < Math.min(23, h + 2); k++) {
        pool.push([residuals[j][k], ws[j] / (1 + Math.abs(k - h))]);
      }
    }
    const errors = quantiles(pool);
    return q.map((v, j) => v * (1 - PARAMS.blend) + (mu[h] + errors[j] * PARAMS.spread) * PARAMS.blend);
  });
}

function forecastCase(c) {
  if (JSON.stringify(c.levels || LEVELS) !== JSON.stringify(LEVELS)) throw Error('Unsupported quantiles');
  const hours = (c.forecast || []).map(r => r.hour).sort((a, b) => a - b);
  if (hours.length !== 23 || hours.some((h, i) => h !== i + 2)) throw Error('Expected hours 2 to 24');
  const t = targetDescriptor(c);
  const donors = (c.comparables || []).map(descriptor).filter(Boolean);
  const ratios = predict(t, donors);
  return { hours: ratios.map((q, h) => ({ hour: h + 2,
    q: q.map(v => Math.max(.0001, Math.min(1e9, Math.round(Math.exp(clip(t.f.first + v, Math.log(.01), Math.log(1e9))) * 1e4) / 1e4))).sort((a, b) => a - b),
  })) };
}

function main() {
  const input = process.env.MAKEFUN_INPUT_DIR || '/input';
  const output = process.env.MAKEFUN_OUTPUT_DIR || '/output';
  fs.mkdirSync(output, { recursive: true });
  for (const file of fs.readdirSync(input).filter(n => n.endsWith('.in')).sort()) {
    const c = JSON.parse(fs.readFileSync(path.join(input, file), 'utf8'));
    fs.writeFileSync(path.join(output, file.slice(0, -3) + '.out'), JSON.stringify(forecastCase(c)) + '\n');
  }
}

if (require.main === module) main();
module.exports = { descriptor, targetDescriptor, prepare, predict, forecastCase, PARAMS };
