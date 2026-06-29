const DEFAULT_COPY = {
  brand: {
    title: 'Project Bluefin Operating System Factory',
    subtitle: 'Cloud Native Linux Desktop Testing — Power to the People',
  },
  mission: {
    headline: 'Factory telemetry for image-based Linux, from source to signed artifact.',
    body: 'Every station publishes evidence: promotion lanes, run lineage, coverage, and explicit unknown states when data is missing.',
  },
  station_labels: ['Source & intent', 'Assemble & bake', 'Verify & triage', 'Trust & ship'],
  trust_labels: ['Signing', 'SBOM', 'Attestation', 'CVE posture', 'Promotion timing'],
  links: [
    { label: 'Actions', href: 'https://github.com/projectbluefin/testing-lab/actions', tone: 'good' },
    { label: 'Refresh data', href: 'https://github.com/projectbluefin/testing-lab/actions/workflows/update-test-results.yml', tone: 'muted' },
    { label: 'Runbook', href: 'https://github.com/projectbluefin/testing-lab/blob/main/RUNBOOK.md', tone: 'muted' },
  ],
  screenshots: [
    { file: 'screenshots/bluefin-testing-smoke-latest.png', title: 'Bluefin testing smoke', suite: 'smoke' },
    { file: 'screenshots/bluefin-lts-testing-smoke-latest.png', title: 'Bluefin LTS testing smoke', suite: 'smoke' },
    { file: 'screenshots/dakota-testing-smoke-latest.png', title: 'Dakota testing smoke', suite: 'smoke' },
  ],
  fabric: {
    label: 'Thunderbolt / USB4 mesh',
    tagline: '40 Gbps node-to-node interconnect.',
    links: [],
  },
};

const DATA = {
  copy: DEFAULT_COPY,
  stats: null,
  history: null,
  telemetry: null,
  derivedTrust: null,
  testSurface: null,
};

const fmt = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'short',
});

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function formatTime(value) {
  if (!value) return 'unknown';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'unknown' : fmt.format(date);
}

function hoursAgo(value) {
  if (!value) return 'unknown';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'unknown';
  const diff = Math.max(0, Date.now() - date.getTime());
  const hours = Math.round(diff / 36e5);
  if (hours < 1) return 'under 1h ago';
  if (hours === 1) return '1h ago';
  return `${hours}h ago`;
}

function minutesLabel(value) {
  if (value == null) return '—';
  if (value < 60) return `${value}m`;
  const hours = Math.floor(value / 60);
  const minutes = value % 60;
  return minutes ? `${hours}h ${minutes}m` : `${hours}h`;
}

function compactNumber(value) {
  return Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

function percent(value) {
  return `${Math.round(value)}%`;
}

function median(values) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : Math.round((sorted[mid - 1] + sorted[mid]) / 2);
}

function loadJson(path, fallback) {
  return fetch(path, { cache: 'no-store' })
    .then((response) => {
      if (!response.ok) throw new Error(`${path}: ${response.status}`);
      return response.json();
    })
    .catch(() => fallback);
}

function runStatusClass(status) {
  if (status === 'passed') return 'pass';
  if (status === 'fail') return 'fail';
  if (status === 'running') return 'run';
  return 'pending';
}

function toDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function dayKey(value) {
  const date = toDate(value);
  if (!date) return null;
  return date.toISOString().slice(0, 10);
}

function deriveHistory(recentRuns) {
  const byDay = new Map();
  for (const run of recentRuns || []) {
    const key = dayKey(run.started_at);
    if (!key) continue;
    const bucket = byDay.get(key) || { date: key, total: 0, passed: 0, running: 0, failed: 0, durations: [] };
    bucket.total += 1;
    if (run.overall === 'passed') bucket.passed += 1;
    if (run.overall === 'running') bucket.running += 1;
    if (run.overall === 'fail') bucket.failed += 1;
    if (run.overall === 'passed' && typeof run.duration_min === 'number') bucket.durations.push(run.duration_min);
    byDay.set(key, bucket);
  }

  return [...byDay.values()]
    .sort((a, b) => a.date.localeCompare(b.date))
    .map((bucket) => ({
      date: bucket.date,
      throughput: bucket.total,
      reliability: bucket.total ? Math.round((bucket.passed / bucket.total) * 100) : 0,
      speed_min: bucket.durations.length ? median(bucket.durations) : 0,
      pressure: bucket.running + bucket.failed,
    }));
}

function sparkBars(values, tone = 'accent') {
  const max = Math.max(...values, 1);
  return values.map((value) => {
    const height = Math.max(14, Math.round((value / max) * 100));
    return `<span class="spark ${tone}" style="height:${height}%"></span>`;
  }).join('');
}

function latestRun(runs) {
  return [...(runs || [])].sort((a, b) => String(b.started_at).localeCompare(String(a.started_at)))[0] || null;
}

function summarizeRuns(runs) {
  const total = runs.length;
  const passed = runs.filter((run) => run.overall === 'passed').length;
  const failed = runs.filter((run) => run.overall === 'fail').length;
  const running = runs.filter((run) => run.overall === 'running').length;
  const complete = runs.filter((run) => run.overall !== 'running').length;
  const durations = runs.filter((run) => run.overall === 'passed' && typeof run.duration_min === 'number').map((run) => run.duration_min);
  return {
    total,
    passed,
    failed,
    running,
    complete,
    passRate: total ? (passed / total) * 100 : 0,
    speed: durations.length ? median(durations) : 0,
  };
}

function recentWindow(runs, days = 7) {
  const dates = [...new Set((runs || []).map((run) => dayKey(run.started_at)).filter(Boolean))].sort();
  return dates.slice(-days);
}

function buildMetricCard({ title, value, subtext, spark, tone }) {
  return `
    <article class="metric">
      <div class="title">
        <h3>${escapeHtml(title)}</h3>
        <span class="badge ${tone}">${escapeHtml(tone)}</span>
      </div>
      <div class="value">${escapeHtml(value)}</div>
      <div class="sparkline" aria-hidden="true">${spark}</div>
      <div class="subtext">${escapeHtml(subtext)}</div>
    </article>
  `;
}

function buildStation({ title, status, body, chip }) {
  return `
    <article class="station">
      <div class="title">
        <h3>${escapeHtml(title)}</h3>
        <span class="status">${escapeHtml(status)}</span>
      </div>
      <div class="badge ${chip.tone}">${escapeHtml(chip.label)}</div>
      <div class="subtext">${escapeHtml(body)}</div>
    </article>
  `;
}

function buildRun(run) {
  const status = runStatusClass(run.overall);
  return `
    <article class="run-row">
      <div class="run-head">
        <div>
          <div class="run-id">${escapeHtml(run.id)}</div>
          <div class="mono">${escapeHtml(run.label || 'cluster-wide')}</div>
        </div>
        <span class="badge ${status}">${escapeHtml(run.overall)}</span>
      </div>
      <div class="meta">
        <span>${escapeHtml(formatTime(run.started_at))}</span>
        <span>${escapeHtml(run.trigger || 'manual')}</span>
        <span>${escapeHtml(minutesLabel(run.duration_min))}</span>
      </div>
    </article>
  `;
}

function buildBug(bug) {
  const area = (bug.area || 'unknown').toLowerCase();
  const tone = area === 'infra' ? 'bad' : area === 'test' ? 'warn' : 'muted';
  return `
    <article class="bug-row">
      <div class="bug-head">
        <div class="bug-title"><a href="${escapeHtml(bug.url)}" target="_blank" rel="noreferrer">#${bug.number} ${escapeHtml(bug.title)}</a></div>
        <span class="badge ${tone}">${escapeHtml(area)}</span>
      </div>
      <div class="meta">
        <span>opened ${escapeHtml(hoursAgo(bug.created_at))}</span>
      </div>
    </article>
  `;
}

function buildScreenshot(item) {
  return `
    <article class="shot">
      <div class="shot-head">
        <div>
          <div class="shot-title">${escapeHtml(item.title)}</div>
          <div class="mono">${escapeHtml(item.file)}</div>
        </div>
        <span class="badge pending">${escapeHtml(item.suite)}</span>
      </div>
      <img src="./${escapeHtml(item.file)}" alt="${escapeHtml(item.title)}">
    </article>
  `;
}

function buildCoverageTable(coverage) {
  const rows = Object.entries(coverage || {});
  if (!rows.length) {
    return '<div class="loading">No coverage snapshot available.</div>';
  }
  return `
    <table class="coverage-table">
      <thead>
        <tr><th>Suite</th><th>Images</th><th>Scenarios</th><th>Failed</th></tr>
      </thead>
      <tbody>
        ${rows.map(([suite, stats]) => `
          <tr>
            <td>${escapeHtml(suite)}</td>
            <td>${escapeHtml(stats.images)}</td>
            <td>${escapeHtml(stats.scenarios)}</td>
            <td>${escapeHtml(stats.failed)}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

function metricById(telemetry, id) {
  return (telemetry?.metrics || []).find((metric) => metric.id === id) || null;
}

function metricValue(metric, fallback = 'unknown') {
  if (!metric || metric.value == null) return fallback;
  if (metric.unit === 'percent') return `${Math.round(metric.value)}%`;
  return String(metric.value);
}

function metricEvidence(metric) {
  const evidence = (metric?.evidence || [])
    .map((ref) => ref?.url)
    .filter(Boolean);
  if (!evidence.length) return 'no source';
  return evidence.map((url) => `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">source</a>`).join(' · ');
}

function buildTelemetryEvidence(telemetry) {
  const metrics = telemetry?.metrics || [];
  if (!metrics.length) {
    return `
      <section class="section">
        <h2>Telemetry evidence</h2>
        <div class="panel">
          <div class="loading">Telemetry evidence unavailable for this snapshot. Metrics are intentionally marked unknown.</div>
          <div class="meta"><a href="./data/factory-telemetry.json" target="_blank" rel="noreferrer">raw telemetry JSON</a></div>
        </div>
      </section>
    `;
  }
  return `
    <section class="section">
      <h2>Telemetry evidence</h2>
      <div class="panel">
        <table class="coverage-table">
          <thead>
            <tr>
              <th>Metric</th>
              <th>Value</th>
              <th>Numerator / denominator</th>
              <th>Window</th>
              <th>Confidence</th>
              <th>Formula</th>
              <th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            ${metrics.map((metric) => `
              <tr>
                <td>${escapeHtml(metric.label || metric.id)}</td>
                <td>${escapeHtml(metricValue(metric, 'unknown'))}</td>
                <td>${escapeHtml(`${metric.numerator}/${metric.denominator}`)}</td>
                <td>${escapeHtml(`${metric.window_hours}h`)}</td>
                <td>${escapeHtml(metric.confidence || 'unknown')}</td>
                <td class="mono">${escapeHtml(metric.formula || 'unknown')}</td>
                <td>${metricEvidence(metric)}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function latestRunsByLabel(runs) {
  const map = new Map();
  for (const run of runs || []) {
    if (!run?.label || map.has(run.label)) continue;
    map.set(run.label, run);
  }
  return map;
}

function fallbackRunQueryUrl(run) {
  if (run?.run_url) return run.run_url;
  if (!run?.id) return 'https://github.com/projectbluefin/testing-lab/actions';
  return `https://github.com/projectbluefin/testing-lab/actions?query=${encodeURIComponent(run.id)}`;
}

function buildPromotionTimeline(runs) {
  const byLabel = latestRunsByLabel(runs);
  const channels = [
    'bluefin:testing',
    'bluefin:stable',
    'bluefin-lts:testing',
    'bluefin-lts:stable',
    'dakota:latest',
  ];

  return `
    <section class="section">
      <h2>Promotion timeline</h2>
      <p class="section-sub">Which image lanes shipped a green build most recently.</p>
      <div class="panel">
        <table class="coverage-table">
          <thead>
            <tr>
              <th>Lane</th>
              <th>Latest run</th>
              <th>Status</th>
              <th>Observed</th>
              <th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            ${channels.map((lane) => {
              const run = byLabel.get(lane);
              const tone = runStatusClass(run?.overall);
              return `
                <tr>
                  <td class="mono">${escapeHtml(lane)}</td>
                  <td>${escapeHtml(run?.id || 'no recent run')}</td>
                  <td>${run ? `<span class="badge ${tone}">${escapeHtml(run.overall)}</span>` : '<span class="badge pending">unknown</span>'}</td>
                  <td>${escapeHtml(run ? formatTime(run.started_at) : 'unknown')}</td>
                  <td>${run ? `<a href="${escapeHtml(fallbackRunQueryUrl(run))}" target="_blank" rel="noreferrer">source</a>` : 'no source'}</td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function buildLineagePanel(telemetry) {
  const collector = telemetry?.lineage?.collector || {};
  const inputs = telemetry?.lineage?.inputs || [];
  const coverage = telemetry?.coverage || {};
  return `
    <section class="section">
      <h2>Lineage & data quality</h2>
      <div class="panel">
        <div class="meta">
          <span>collector run: ${collector.run_url ? `<a href="${escapeHtml(collector.run_url)}" target="_blank" rel="noreferrer">source</a>` : 'unknown'}</span>
          <span>collector commit: ${collector.commit_url ? `<a href="${escapeHtml(collector.commit_url)}" target="_blank" rel="noreferrer">source</a>` : 'unknown'}</span>
          <span>input digest: <span class="mono">${escapeHtml(telemetry?.lineage?.inputs_digest_sha256 || 'unknown')}</span></span>
          <span>coverage: ${escapeHtml(`${coverage.observed_result_docs ?? 0}/${coverage.expected_result_docs ?? 0}`)} (${escapeHtml(metricValue({ value: (coverage.coverage_ratio || 0) * 100, unit: 'percent' }))})</span>
        </div>
        <table class="coverage-table" style="margin-top: 12px">
          <thead>
            <tr><th>Input path</th><th>Digest</th></tr>
          </thead>
          <tbody>
            ${inputs.length ? inputs.slice(0, 8).map((input) => `
              <tr>
                <td class="mono">${escapeHtml(input.path || 'unknown')}</td>
                <td class="mono">${escapeHtml(input.sha256 || 'unknown')}</td>
              </tr>
            `).join('') : '<tr><td colspan="2">No lineage inputs published.</td></tr>'}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function buildTourMap(stations) {
  return `
    <section class="section">
      <h2>Factory flow map</h2>
      <div class="station-grid">
        ${stations.map((station) => `
          <article class="station">
            <div class="title">
              <h3>${escapeHtml(station.title)}</h3>
              <span class="status">${escapeHtml(station.chip.label)}</span>
            </div>
            <div class="badge ${station.chip.tone}">${escapeHtml(station.status)}</div>
            <div class="subtext">${escapeHtml(station.body)}</div>
          </article>
        `).join('')}
      </div>
    </section>
  `;
}

const RIGOR_LADDER = [
  { id: 'builds-pass', name: 'Builds pass', def: 'CI is green: code compiles, images build, tests don\u2019t crash.', achieved: true },
  { id: 'numbers',     name: 'Numbers, not vibes', def: 'Pass rates ship with sample size attached \u2014 counts come from results files, not gut feel.', achieved: true },
  { id: 'confidence',  name: 'Honest confidence', def: 'Each pass rate has a confidence range so small samples can\u2019t pretend to be certainty.', achieved: true, current: true },
  { id: 'reproducible', name: 'Reruns reproduce', def: 'Anyone re-derives every number on this page from signed inputs and a pinned notebook.', achieved: false },
  { id: 'regression',  name: 'Regressions auto-detected', def: 'Statistical change-point detection flags drops without a human staring at the chart.', achieved: false },
  { id: 'slo-backed',  name: 'Bound by SLOs', def: 'Every failure mode has a service-level objective and error budget; breaches automatically open work.', achieved: false },
];

function buildRigorLadder() {
  const rungs = RIGOR_LADDER.map((r, i) => {
    const state = r.current ? 'current' : (r.achieved ? 'achieved' : 'future');
    const mark = r.current ? '\u2192' : (r.achieved ? '\u2713' : '\u25a2');
    return `
      <li class="rigor-rung rigor-${state}">
        <div class="rigor-head">
          <span class="rigor-mark" aria-hidden="true">${mark}</span>
          <span class="rigor-step">Step ${i + 1}</span>
          <span class="rigor-name">${escapeHtml(r.name)}</span>
          ${r.current ? '<span class="rigor-badge">we are here</span>' : ''}
        </div>
        <p class="rigor-def">${escapeHtml(r.def)}</p>
      </li>
    `;
  }).join('');
  return `
    <div class="rigor-ladder" aria-label="Rigor ladder">
      <div class="rigor-ladder-head">
        <span class="rigor-ladder-label">How rigorous are these numbers?</span>
        <span class="rigor-ladder-tagline">Each rung is a level the factory either has reached or hasn\u2019t yet. Future rungs are shown so you can see what comes next.</span>
      </div>
      <ol class="rigor-rungs">${rungs}</ol>
    </div>
  `;
}

function tilePassRateHistory(metric) {
  const hist = metric?.history || metric?.samples;
  if (Array.isArray(hist) && hist.length) {
    return hist
      .map((p) => (typeof p === 'number' ? p : p?.value))
      .filter((v) => typeof v === 'number')
      .map((v) => v <= 1 ? v * 100 : v);
  }
  return [];
}

function sparkPolyline(values, { width = 120, height = 28, tone = 'accent' } = {}) {
  if (!values.length) {
    return `<svg class="tile-spark empty" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true"><line x1="0" y1="${height - 1}" x2="${width}" y2="${height - 1}"></line></svg>`;
  }
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 100);
  const span = Math.max(max - min, 1);
  const stepX = width / Math.max(values.length - 1, 1);
  const pts = values.map((v, i) => {
    const x = i * stepX;
    const y = height - ((v - min) / span) * (height - 2) - 1;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return `<svg class="tile-spark ${tone}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"></polyline></svg>`;
}

function buildTrustWindowSection(derived) {
  if (!derived || !Array.isArray(derived.metrics) || derived.metrics.length === 0) {
    return `
    <section class="section twpr-section" id="trust-window-pass-rate">
      <div class="twpr-heading">
        <h2>Pass rate, with honest confidence</h2>
        <p class="section-sub">How often each build passes its tests \u2014 reported with a confidence range so small samples don\u2019t lie.</p>
        <p class="twpr-intro">No derived data yet. The hourly derive workflow has not committed output. See <a href="./about/methodology.html">methodology</a>.</p>
      </div>
      ${buildRigorLadder()}
    </section>`;
  }
  // De-duplicate by (variant, branch, suite); keep the most recent per cell.
  const byKey = new Map();
  for (const m of derived.metrics) {
    const c = m?.context || {};
    const key = `${c.variant || '?'}|${c.branch || '?'}|${c.suite || '?'}`;
    const existing = byKey.get(key);
    if (!existing || String(m.observed_at || m.window_end || '').localeCompare(String(existing.observed_at || existing.window_end || '')) > 0) {
      byKey.set(key, m);
    }
  }
  const tiles = [...byKey.values()].sort((a, b) => (a.id || '').localeCompare(b.id || ''));
  const gen = derived.generator || {};
  return `
  <section class="section twpr-section" id="trust-window-pass-rate">
    <div class="twpr-heading">
      <h2>Pass rate, with honest confidence</h2>
      <p class="section-sub">How often each build passes its tests \u2014 reported with a confidence range so small samples don\u2019t lie.</p>
      <p class="twpr-intro">
        Method: <a href="./about/methodology.html#trust_window_pass_rate">Wilson 95% confidence interval</a> \u00b7 Notebook: <a href="./methods/01_pass_rate_wilson.html">01_pass_rate_wilson.html</a>${gen.commit_sha ? ` \u00b7 Generated from <span class="mono">${escapeHtml(String(gen.commit_sha).slice(0, 7))}</span>` : ''}
      </p>
    </div>
    ${buildRigorLadder()}
    ${tiles.length === 0
      ? `<p class="twpr-empty">No records.</p>`
      : `<div class="twpr-grid">${tiles.map(buildTwprTile).join('')}</div>`}
  </section>`;
}

function buildTwprTile(m) {
  const ctx = m.context || {};
  const pct = m.value == null ? '\u2014' : (m.value * 100).toFixed(1) + '%';
  const lo = m.ci_lower == null ? '\u2014' : (m.ci_lower * 100).toFixed(1);
  const hi = m.ci_upper == null ? '\u2014' : (m.ci_upper * 100).toFixed(1);
  const n = (m.n == null ? '\u2014' : m.n);
  const activeFMs = (m.failure_modes || []).filter((f) => f.active);
  const stateTone = m.state === 'fresh' ? 'good' : (m.state === 'degraded' ? 'bad' : 'warn');
  const fmChip = activeFMs.length > 0
    ? `<details class="twpr-fmea"><summary class="twpr-fmea-chip twpr-fmea-active" title="${activeFMs.length} active failure mode${activeFMs.length === 1 ? '' : 's'}">\u26a0 ${activeFMs.length} active</summary><ul>${activeFMs.map((f) => `<li><strong>${escapeHtml(f.id)}</strong>: ${escapeHtml(f.description)}</li>`).join('')}</ul></details>`
    : `<span class="twpr-fmea-chip twpr-fmea-clean" title="No active failure modes">FMEA clean</span>`;
  const history = tilePassRateHistory(m);
  return `
    <article class="twpr-tile">
      <header class="twpr-tile-header">
        <span class="twpr-key mono">${escapeHtml(ctx.variant || '?')}/${escapeHtml(ctx.branch || '?')}/${escapeHtml(ctx.suite || '?')}</span>
        <span class="chip ${stateTone}">${escapeHtml(m.state || 'unknown')}</span>
      </header>
      <div class="twpr-value">${pct}</div>
      <div class="twpr-ci">95% CI [${lo}, ${hi}]% \u00b7 <span class="mono">n=${escapeHtml(String(n))}</span></div>
      ${sparkPolyline(history, { tone: 'accent' })}
      <div class="twpr-method">Wilson 95% \u00b7 confidence ${escapeHtml(m.confidence || 'unknown')}</div>
      <div class="twpr-fmea-row">${fmChip}</div>
    </article>`;
}

function buildFabricStrip(fabric, nodes) {
  if (!fabric || !Array.isArray(fabric.links) || !fabric.links.length) return '';
  const known = new Set((nodes || []).map((n) => n.name).filter(Boolean));
  const items = fabric.links.map((link) => {
    const a = link.a || '?';
    const b = link.b || '?';
    const speed = link.speed_gbps ? `${link.speed_gbps} Gbps` : 'link';
    const tech = link.tech || 'USB4';
    const aOnline = known.has(a);
    const bOnline = known.has(b);
    const tone = (aOnline && bOnline) ? 'good' : 'muted';
    return `
      <li class="fabric-link ${tone}">
        <span class="fabric-end ${aOnline ? '' : 'offline'} mono">${escapeHtml(a)}</span>
        <span class="fabric-pipe" aria-hidden="true">
          <span class="fabric-pulse"></span>
          <span class="fabric-speed">${escapeHtml(speed)}</span>
        </span>
        <span class="fabric-end ${bOnline ? '' : 'offline'} mono">${escapeHtml(b)}</span>
        <span class="fabric-tech chip muted">${escapeHtml(tech)}</span>
      </li>
    `;
  }).join('');
  return `
    <div class="fabric-strip" aria-label="Thunderbolt/USB4 fabric">
      <div class="fabric-head">
        <span class="fabric-label">${escapeHtml(fabric.label || 'Thunderbolt / USB4 mesh')}</span>
        ${fabric.tagline ? `<span class="fabric-tagline">${escapeHtml(fabric.tagline)}</span>` : ''}
      </div>
      <ul class="fabric-links">${items}</ul>
    </div>
  `;
}

function buildClusterNodesPanel(nodes, summary, freshness, telemetrySnapshot, openBugsCount) {
  const totalRam = nodes.reduce((sum, n) => sum + (n.ram_gb || 0), 0);
  const totalCpu = nodes.reduce((sum, n) => sum + (n.cpu_threads || 0), 0);
  const snapTone = telemetrySnapshot.state === 'fresh' ? 'good' : telemetrySnapshot.state === 'degraded' ? 'bad' : 'warn';
  return `
    <section class="section nodes-section">
      <div class="nodes-header">
        <span class="label">Contributor Clusters \u2014 Live Snapshot</span>
        <div class="nodes-summary">
          <span class="chip ${snapTone}">snapshot <strong>${escapeHtml(telemetrySnapshot.state || 'unknown')}</strong></span>
          <span class="chip muted">refreshed <strong>${escapeHtml(hoursAgo(freshness))}</strong></span>
          <span class="chip muted">runs in window <strong>${escapeHtml(summary.total)}</strong></span>
          <span class="chip ${summary.failed ? 'bad' : 'good'}">failing <strong>${escapeHtml(summary.failed)}</strong></span>
          <span class="chip muted">open bugs <strong><a href="https://github.com/projectbluefin/testing-lab/issues?q=is%3Aissue+is%3Aopen+label%3Abug" target="_blank" rel="noreferrer">${escapeHtml(openBugsCount)}</a></strong></span>
        </div>
      </div>
      <p class="section-sub">Who\u2019s donating cycles to test Bluefin right now \u2014 each card is a real machine running real tests.</p>
      ${buildFabricStrip(DATA.copy?.fabric, nodes)}
      <div class="nodes-grid">
        ${nodes.length ? nodes.map((node) => `
          <article class="node-card">
            <header>
              <h3 class="mono">${escapeHtml(node.name)}</h3>
              <span class="badge ${node.status === 'ready' ? 'pass' : 'fail'}">${escapeHtml(node.status)}</span>
            </header>
            <div class="node-role">${escapeHtml(node.role)}</div>
            <div class="node-stats">
              <span class="chip muted"><strong>${escapeHtml(node.cpu_threads)}</strong> threads</span>
              <span class="chip muted"><strong>${escapeHtml(node.ram_gb)}</strong> GB RAM</span>
            </div>
          </article>
        `).join('') : '<div class="loading">No cluster snapshot.</div>'}
        <article class="node-card node-card-total">
          <header><h3>Cluster total</h3></header>
          <div class="node-role">${escapeHtml(nodes.length)} nodes</div>
          <div class="node-stats">
            <span class="chip muted"><strong>${escapeHtml(totalCpu)}</strong> threads</span>
            <span class="chip muted"><strong>${escapeHtml(totalRam)}</strong> GB RAM</span>
          </div>
        </article>
      </div>
    </section>
  `;
}

function describeRun(run) {
  const id = String(run.id || '');
  const label = run.label || 'cluster-wide';
  const lower = id.toLowerCase();
  if (/^build-cd-sync[-/]/.test(lower)) return `Building and syncing ${label}`;
  if (/^build[-/]/.test(lower)) return `Building ${label}`;
  if (/(^|-)smoke(-|$)/.test(lower)) return `Smoke test for ${label}`;
  if (/^provision[-/]/.test(lower)) return `Provisioning ${label} VM`;
  if (/^teardown[-/]/.test(lower)) return `Tearing down ${label} VM`;
  if (/^promote[-/]/.test(lower) || /-promote-/.test(lower)) return `Promoting ${label}`;
  if (/^poll[-/]/.test(lower) || /-poller$/.test(lower) || /^image-poll[-/]/.test(lower)) return `Polling ${label} for new image digests`;
  if (/(^|-)pr-/.test(lower) || /^pr[-/]/.test(lower)) return `PR validation for ${label}`;
  if (/cleanup|gc(-|$)/.test(lower)) return `Cleanup pass on ${label}`;
  if (/^nightly[-/]/.test(lower)) return `Nightly run for ${label}`;
  if (/^run-/.test(lower) || /-tests?(-|$)/.test(lower)) return `Running tests against ${label}`;
  // Generic fallback: humanize the leading hyphen-separated verbs.
  const head = id.split('-').slice(0, 3).join(' ');
  return `${head} for ${label}`;
}

function buildRecentRunsChangelog(runs) {
  if (!runs.length) {
    return '<section class="section"><h2>Recent runs</h2><div class="panel"><div class="loading">No runs in window.</div></div></section>';
  }
  const rows = runs.slice(0, 20).map((run) => {
    const status = runStatusClass(run.overall);
    const dot = run.overall === 'passed' ? '●' : run.overall === 'running' ? '◌' : run.overall === 'fail' ? '●' : '○';
    return `
      <li class="changelog-row">
        <span class="changelog-dot ${status}" aria-hidden="true">${dot}</span>
        <div class="changelog-main">
          <a class="changelog-label mono" href="${escapeHtml(fallbackRunQueryUrl(run))}" target="_blank" rel="noreferrer">${escapeHtml(run.id)}</a>
          <div class="changelog-desc">${escapeHtml(describeRun(run))}</div>
        </div>
        <div class="changelog-time">
          <span>${escapeHtml(hoursAgo(run.started_at))}</span>
          <span class="muted">${escapeHtml(formatTime(run.started_at))}</span>
        </div>
        <div class="changelog-extra">
          <span class="chip muted">${escapeHtml(minutesLabel(run.duration_min))}</span>
          <span class="chip muted">${escapeHtml(run.trigger || 'manual')}</span>
          <span class="badge ${status}">${escapeHtml(run.overall)}</span>
        </div>
      </li>
    `;
  }).join('');
  return `
    <section class="section">
      <div class="section-head">
        <h2>Recent runs</h2>
        <a class="section-link" href="https://github.com/projectbluefin/testing-lab/actions" target="_blank" rel="noreferrer">all runs on GitHub Actions \u2192</a>
      </div>
      <p class="section-sub">Most recent workflow attempts and what each one was trying to do.</p>
      <ol class="changelog">${rows}</ol>
    </section>
  `;
}

function suiteResultBaseName(cell) {
  return cell.results_path.replace(/^results\//, '').replace(/\.json$/, '');
}

function buildTestSurface(surface, runs) {
  if (!surface || !surface.length) {
    return '<section class="section"><h2>Test surface</h2><div class="panel"><div class="loading">No test surface manifest.</div></div></section>';
  }
  const runByLabel = new Map();
  for (const r of runs || []) {
    if (r?.label && !runByLabel.has(r.label)) runByLabel.set(r.label, r);
  }
  const cellsHtml = surface.map((cell) => {
    const screenshotUrl = cell.screenshot_path ? `./${cell.screenshot_path}` : null;
    const resultsUrl = `./${cell.results_path}`;
    const repoUrl = `https://github.com/projectbluefin/testing-lab/blob/main/docs/${cell.results_path}`;
    const labelCandidates = [
      `${cell.variant}:${cell.branch}`,
      `${cell.variant}-${cell.branch}`,
    ];
    const matchingRun = labelCandidates.map((l) => runByLabel.get(l)).find(Boolean);
    const runTone = matchingRun ? runStatusClass(matchingRun.overall) : 'pending';
    const runText = matchingRun ? matchingRun.overall : 'no recent run';
    const imgHtml = screenshotUrl
      ? `<img class="surface-shot" src="${escapeHtml(screenshotUrl)}" alt="${escapeHtml(cell.variant)}/${escapeHtml(cell.suite)} latest capture" loading="lazy">`
      : `<div class="surface-shot surface-shot-missing"><span>no capture published</span></div>`;
    return `
      <article class="surface-cell">
        ${imgHtml}
        <div class="surface-meta">
          <div class="surface-key mono">${escapeHtml(cell.variant)}/<span class="muted">${escapeHtml(cell.branch)}</span>/<strong>${escapeHtml(cell.suite)}</strong></div>
          <div class="surface-row">
            <span class="badge ${runTone}">${escapeHtml(runText)}</span>
            <a class="surface-link mono" href="${escapeHtml(resultsUrl)}" target="_blank" rel="noreferrer">results.json</a>
            <a class="surface-link mono" href="${escapeHtml(repoUrl)}" target="_blank" rel="noreferrer">repo</a>
          </div>
        </div>
      </article>
    `;
  }).join('');
  const withShot = surface.filter((c) => c.screenshot_path).length;
  return `
    <section class="section">
      <div class="section-head">
        <h2>Test surface</h2>
        <span class="section-meta muted">${escapeHtml(surface.length)} expected (variant \u00d7 branch \u00d7 suite) \u00b7 <strong>${escapeHtml(withShot)}</strong> with screenshot \u00b7 <strong>${escapeHtml(surface.length - withShot)}</strong> missing</span>
      </div>
      <p class="section-sub">Every (variant \u00d7 branch \u00d7 suite) combination the factory promises to cover, and whether we have a fresh screenshot for it.</p>
      <div class="surface-grid">${cellsHtml}</div>
    </section>
  `;
}

function render(copy, stats, history, telemetry) {
  const root = document.getElementById('factory-dashboard');
  const runs = Array.isArray(stats?.recent_runs) ? stats.recent_runs : [];
  const openBugs = Array.isArray(stats?.open_bugs) ? stats.open_bugs : [];
  const clusterNodes = stats?.factory?.cluster?.nodes || [];
  const coverage = stats?.test_coverage?.coverage_by_suite || {};
  const summary = summarizeRuns(runs);
  const freshness = stats?._meta?.refreshed_at || stats?._meta?.generated;
  const telemetrySnapshot = telemetry?.snapshot || {};
  const surface = DATA.testSurface?.surface || [];

  root.innerHTML = `
    <header class="topbar">
      <div class="brand">
        <h1>${escapeHtml(copy.brand.title)}</h1>
        <p>${escapeHtml(copy.brand.subtitle)}</p>
      </div>
      <div class="link-row">
        ${copy.links.map((link) => `<a class="link-pill" href="${escapeHtml(link.href)}" target="_blank" rel="noreferrer">${escapeHtml(link.label)}</a>`).join('')}
      </div>
    </header>

    ${buildClusterNodesPanel(clusterNodes, summary, freshness, telemetrySnapshot, openBugs.length)}

    ${buildTrustWindowSection(DATA.derivedTrust)}

    ${buildRecentRunsChangelog(runs)}

    ${buildTestSurface(surface, runs)}

    ${buildPromotionTimeline(runs)}

    ${buildTelemetryEvidence(telemetry)}

    <section class="section">
      <h2>Coverage by suite</h2>
      <div class="panel">
        ${buildCoverageTable(coverage)}
      </div>
    </section>

    ${buildLineagePanel(telemetry)}

    <div class="footer">
      Snapshot generated ${escapeHtml(formatTime(stats?._meta?.generated))} · refreshed ${escapeHtml(formatTime(stats?._meta?.refreshed_at))} · source: <a href="https://github.com/projectbluefin/testing-lab/blob/main/docs/" target="_blank" rel="noreferrer">repo</a>
    </div>
  `;
  attachTwprTabs(root);
}

function attachTwprTabs(root) {
  const tabs = root.querySelectorAll('.twpr-tab');
  if (!tabs.length) return;
  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      const target = tab.getAttribute('data-audience');
      root.querySelectorAll('.twpr-tab').forEach((t) => t.classList.toggle('active', t === tab));
      root.querySelectorAll('.twpr-panel').forEach((p) => p.classList.toggle('active', p.getAttribute('data-audience-panel') === target));
    });
  });
}

async function main() {
  const [copy, stats, history, telemetry, derivedTrust, testSurface] = await Promise.all([
    loadJson('./data/factory-copy.json', DEFAULT_COPY),
    loadJson('./data/factory-stats.json', { recent_runs: [], open_bugs: [], _meta: {}, test_coverage: {}, factory: { cluster: { nodes: [], total_ram_gb: 0 } } }),
    loadJson('./data/factory-history.json', { rollups: [] }),
    loadJson('./data/factory-telemetry.json', { snapshot: {}, metrics: [], coverage: {}, lineage: {}, errors: [] }),
    loadJson('./data/derived/trust_window_pass_rate.json', null),
    loadJson('./data/test-surface.json', { surface: [] }),
  ]);
  DATA.copy = copy;
  DATA.stats = stats;
  DATA.history = history;
  DATA.telemetry = telemetry;
  DATA.derivedTrust = derivedTrust;
  DATA.testSurface = testSurface;
  render(copy, stats, history, telemetry);
}

main().catch((error) => {
  const root = document.getElementById('factory-dashboard');
  root.innerHTML = `<div class="error">Factory dashboard failed to load: ${escapeHtml(error.message)}</div>`;
});
