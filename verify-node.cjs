// Same leave-one-launch-out folds for the previous analog model and ridge blend.
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const os = require('node:os');
const { performance } = require('node:perf_hooks');
const model = require('./main.ts');
const input = path.join(__dirname, 'gta6-twitch-ccu-forecast-01-kit/input');
const tau = [.05, .25, .5, .75, .95];
const median = a => a.sort((a, b) => a - b)[a.length >> 1];
const case0 = JSON.parse(fs.readFileSync(path.join(input, 'p00.in')));
const donors = case0.comparables.map(model.descriptor).filter(d => d && d.full);
// Exercise final-shaped optional context and missing-history fallbacks without
// inventing unseen final viewer counts or asserting their forecast accuracy.
const synthetic = JSON.parse(JSON.stringify(case0));
synthetic.id = 'h00';
synthetic.streams = [{ login: 'fixture', viewers: 1000, language: 'en', started_at: synthetic.day_start }];
synthetic.categories_hourly = [{ from: synthetic.day_start, top: [{ name: 'fixture', viewers: 1000, channels: 2 }] }];
synthetic.comparables.push(...case0.comparables.slice(0, 4));
const fullContext = model.forecastCase(synthetic);
if (JSON.stringify(fullContext) !== JSON.stringify(model.forecastCase(synthetic))) throw Error('Final-shaped determinism');
const missing = { ...synthetic, history: [], history_hourly: [], comparables: [] };
if (model.forecastCase(missing).hours.some(r => r.q.some(v => !Number.isFinite(v) || v <= 0))) throw Error('Fallback');
const renamed = { ...case0, id: 'arbitrary-id', game: { name: 'arbitrary-name', twitch_id: '0' } };
if (JSON.stringify(model.forecastCase(renamed)) !== JSON.stringify(model.forecastCase(case0))) throw Error('Identity-dependent prediction');
const metrics = {};
const foldDetails = [];
for (let i = 0; i < donors.length; i++) {
  const target = donors[i], train = donors.filter((_, j) => j !== i);
  const prepared = model.prepare(train);
  const fold = { name: target.name, console: target.console };
  for (const mode of ['analog', 'blend']) {
    const pred = model.predict(target, train, prepared, mode);
    const costs = [];
    let covered = 0;
    for (let h = 0; h < 23; h++) {
      const y = target.y[h];
      for (let j = 0; j < 5; j++) {
        const error = y - pred[h][j];
        costs.push(2 * Math.max(tau[j] * error, (tau[j] - 1) * error));
      }
      covered += pred[h][0] <= y && y <= pred[h][4] ? 1 : 0;
    }
    fold[mode] = costs.reduce((a, b) => a + b, 0) / costs.length;
    for (const group of ['all', ...(target.console ? ['console'] : [])]) {
      const key = mode + '_' + group;
      const metric = metrics[key] ||= { sum: 0, items: 0, covered: 0, hours: 0 };
      metric.sum += costs.reduce((a, b) => a + b, 0);
      metric.items += costs.length; metric.covered += covered; metric.hours += 23;
    }
  }
  foldDetails.push(fold);
}
for (const metric of Object.values(metrics)) {
  metric.loss = metric.sum / metric.items;
  metric.coverage90 = metric.covered / metric.hours;
  delete metric.sum;
}
const scratch = fs.mkdtempSync(path.join(__dirname, '.audit/node-'));
const cases = {};
try {
  for (const file of fs.readdirSync(input).filter(n => n.endsWith('.in')).sort()) {
    const dir = path.join(scratch, file.slice(0, -3));
    fs.mkdirSync(dir);
    fs.copyFileSync(path.join(input, file), path.join(dir, file));
    const out = path.join(dir, 'out');
    const times = []; let first;
    for (let i = 0; i < 12; i++) {
      const start = performance.now();
      const child = cp.spawnSync(process.env.NODE22 || process.execPath, [path.join(__dirname, 'main.ts')], {
        env: { ...process.env, MAKEFUN_INPUT_DIR: dir, MAKEFUN_OUTPUT_DIR: out }, encoding: 'utf8', timeout: 8000,
      });
      times.push(performance.now() - start);
      if (child.status !== 0) throw Error(child.stderr);
      const bytes = fs.readFileSync(path.join(out, file.slice(0, -3) + '.out'));
      if (first && !first.equals(bytes)) throw Error('Nondeterminism: ' + file);
      first = bytes;
      const doc = JSON.parse(bytes);
      if (Object.keys(doc).join() !== 'hours' || doc.hours.length !== 23) throw Error('Shape');
      doc.hours.forEach((r, h) => {
        if (r.hour !== h + 2 || r.q.length !== 5 || Object.keys(r).sort().join() !== 'hour,q'
            || r.q.some((v, j) => !(v > 0 && v <= 1e9 && Number.isFinite(v)) || j > 0 && v < r.q[j - 1])) throw Error('Quantiles');
      });
    }
    cases[file] = { deterministic: true, valid: true, bytes: first.length,
      median_ms: median(times.slice(2)), min_ms: Math.min(...times.slice(2)), max_ms: Math.max(...times.slice(2)) };
  }
} finally { fs.rmSync(scratch, { recursive: true, force: true }); }
const report = { runtime: process.env.NODE22 || process.version, host: process.platform,
  note: 'Official practice outcomes unavailable locally. Historical folds exclude outer target from residual calibration.',
  params: model.PARAMS, metrics, foldDetails, cases };
report.average_case_median_ms = Object.values(cases).reduce((sum, c) => sum + c.median_ms, 0) / 4;
report.prediction_changes_are_intentional = true;
fs.writeFileSync(path.join(__dirname, '.audit/node-validation.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify({ ...report, foldDetails: undefined }, null, 2));
