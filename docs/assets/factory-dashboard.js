const DEFAULT_COPY = {
  brand: {
    title: 'Factory Tour',
    subtitle: 'Bluefin QA operations dashboard',
  },
  mission: {
    headline: 'Ship image-based changes with evidence, not vibes.',
    body: 'Live runs, failing work, and cluster health stay on one page so operators can tell whether the factory is moving or stalled.',
  },
  station_labels: ['Source', 'Assembly', 'Verification', 'Trust'],
  trust_labels: ['Signing', 'SBOM', 'Attestation', 'CVE posture', 'Promotion timing'],
  links: [
    { label: 'Argo UI', href: 'https://192.168.1.102:32746', tone: 'good' },
    { label: 'Refresh data', href: 'https://github.com/projectbluefin/testing-lab/actions/workflows/update-test-results.yml', tone: 'muted' },
    { label: 'Runbook', href: 'https://github.com/projectbluefin/testing-lab/blob/main/RUNBOOK.md', tone: 'muted' },
  ],
  screenshots: [
    { file: 'screenshots/bluefin-testing-smoke-latest.png', title: 'Bluefin testing smoke', suite: 'smoke' },
    { file: 'screenshots/bluefin-lts-testing-smoke-latest.png', title: 'Bluefin LTS testing smoke', suite: 'smoke' },
    { file: 'screenshots/dakota-testing-smoke-latest.png', title: 'Dakota testing smoke', suite: 'smoke' },
  ],
};

const DATA = {
  copy: DEFAULT_COPY,
  stats: null,
  history: null,
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

function render(copy, stats, history) {
  const root = document.getElementById('factory-dashboard');
  const runs = Array.isArray(stats?.recent_runs) ? stats.recent_runs : [];
  const openBugs = Array.isArray(stats?.open_bugs) ? stats.open_bugs : [];
  const clusterNodes = stats?.factory?.cluster?.nodes || [];
  const coverage = stats?.test_coverage?.coverage_by_suite || {};
  const latest = latestRun(runs);
  const summary = summarizeRuns(runs);
  const historySeries = (history?.rollups?.length ? history.rollups : deriveHistory(runs)).slice(-7);
  const throughputSeries = historySeries.map((entry) => entry.throughput || 0);
  const reliabilitySeries = historySeries.map((entry) => entry.reliability || 0);
  const speedSeries = historySeries.map((entry) => entry.speed_min || 0);
  const pressureSeries = historySeries.map((entry) => entry.pressure || 0);
  const freshness = stats?._meta?.refreshed_at || stats?._meta?.generated;
  const liveOk = stats?._meta?.live_snapshot_ok;

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

    <section class="hero">
      <div class="hero-copy">
        <span class="label">Mission brief</span>
        <h2>${escapeHtml(copy.mission.headline)}</h2>
        <p>${escapeHtml(copy.mission.body)}</p>
        <div class="pill-row">
          <span class="pill ${liveOk ? 'good' : 'warn'}"><strong>${liveOk ? 'live' : 'partial'}</strong> snapshot</span>
          <span class="pill muted">refreshed ${escapeHtml(hoursAgo(freshness))}</span>
          <span class="pill muted">${escapeHtml(summary.total)} recent runs</span>
          <span class="pill muted">${escapeHtml(openBugs.length)} open bugs</span>
        </div>
      </div>
      <aside class="hero-aside">
        <span class="label">Current readout</span>
        <div class="pill-row">
          <span class="chip ${summary.failed ? 'bad' : 'good'}">pass rate <strong>${escapeHtml(percent(summary.passRate))}</strong></span>
          <span class="chip ${summary.running ? 'warn' : 'good'}">running <strong>${escapeHtml(summary.running)}</strong></span>
          <span class="chip muted">median speed <strong>${escapeHtml(minutesLabel(summary.speed))}</strong></span>
          <span class="chip muted">cluster RAM <strong>${escapeHtml(compactNumber(stats?.factory?.cluster?.total_ram_gb || 0))} GB</strong></span>
        </div>
        <div style="margin-top: 14px" class="meta">
          <span>latest run: ${escapeHtml(latest?.id || 'none')}</span>
          <span>${escapeHtml(latest?.label || 'n/a')}</span>
          <span>${escapeHtml(formatTime(latest?.started_at))}</span>
        </div>
        <div class="label" style="margin-top: 14px">Cluster nodes</div>
        <div class="pill-row">
          ${clusterNodes.length ? clusterNodes.map((node) => `
            <span class="pill ${node.status === 'ready' ? 'good' : 'bad'}">
              <strong>${escapeHtml(node.name)}</strong>
              ${escapeHtml(node.status)}
              ${escapeHtml(node.role)}
            </span>
          `).join('') : '<span class="pill muted">no cluster snapshot</span>'}
        </div>
      </aside>
    </section>

    <section class="section">
      <div class="metric-grid">
        ${buildMetricCard({
          title: 'Speed to release',
          value: minutesLabel(summary.speed),
          subtext: 'Median duration of passed runs in the current window.',
          spark: sparkBars(speedSeries.map((value) => value || 0)),
          tone: 'good',
        })}
        ${buildMetricCard({
          title: 'Throughput',
          value: compactNumber(summary.total),
          subtext: 'Runs surfaced in the live window.',
          spark: sparkBars(throughputSeries),
          tone: 'run',
        })}
        ${buildMetricCard({
          title: 'Reliability',
          value: percent(summary.passRate),
          subtext: `${summary.failed} failures among ${summary.complete} completed runs.`,
          spark: sparkBars(reliabilitySeries),
          tone: summary.failed ? 'warn' : 'good',
        })}
        ${buildMetricCard({
          title: 'Queue pressure',
          value: compactNumber(summary.running),
          subtext: 'Active workflows still moving through the factory.',
          spark: sparkBars(pressureSeries),
          tone: summary.running ? 'warn' : 'good',
        })}
      </div>
    </section>

    <section class="section">
      <h2>Stations</h2>
      <div class="station-grid">
        ${buildStation({
          title: copy.station_labels[0],
          status: `${summary.total} runs`,
          body: 'Fresh work enters through pollers and manual dispatch before the dashboard snapshot lands.',
          chip: { label: latest?.trigger || 'manual', tone: 'run' },
        })}
        ${buildStation({
          title: copy.station_labels[1],
          status: `${compactNumber(stats?.test_coverage?.scenarios_total || 0)} scenarios`,
          body: 'The current coverage snapshot shows whether the image matrix is broad enough to trust.',
          chip: { label: `${compactNumber(stats?.test_coverage?.images_with_results || 0)} images`, tone: 'good' },
        })}
        ${buildStation({
          title: copy.station_labels[2],
          status: `${summary.failed} failing`,
          body: 'Failing runs and open bugs stay adjacent so triage can move directly from symptom to owner.',
          chip: { label: `${summary.complete} complete`, tone: summary.failed ? 'bad' : 'good' },
        })}
        ${buildStation({
          title: copy.station_labels[3],
          status: `${openBugs.length} open bugs`,
          body: 'Trust keeps the image contract honest: the open-issue count, snapshot health, and promotion cadence.',
          chip: { label: liveOk ? 'live' : 'stale', tone: liveOk ? 'good' : 'warn' },
        })}
      </div>
    </section>

    <section class="section">
      <h2>Trust layer</h2>
      <div class="trust-row">
        ${copy.trust_labels.map((label, index) => `
          <article class="trust-item">
            <div class="title">
              <h3>${escapeHtml(label)}</h3>
              <span class="badge ${index < 2 ? 'pass' : index === 2 ? 'run' : 'pending'}">${index < 2 ? 'checked' : index === 2 ? 'queued' : 'watch'}</span>
            </div>
            <div class="subtext">
              ${index === 0 ? 'Image signatures and runtime provenance close the loop on what was actually shipped.' :
                index === 1 ? 'SBOM generation and artifact traceability keep the release surface reviewable.' :
                index === 2 ? 'Attestation links the image to the run that produced it.' :
                index === 3 ? `${openBugs.length} issues remain open in the current snapshot.` :
                `Last refresh was ${escapeHtml(hoursAgo(freshness))}.`}
            </div>
          </article>
        `).join('')}
      </div>
    </section>

    <section class="split section">
      <article class="panel">
        <h2>Recent runs</h2>
        <div class="run-grid">
          ${runs.slice(0, 8).map(buildRun).join('')}
        </div>
      </article>
      <article class="panel">
        <h2>Open bugs</h2>
        <div class="bug-grid">
          ${openBugs.slice(0, 8).map(buildBug).join('')}
        </div>
      </article>
    </section>

    <section class="section">
      <h2>Coverage</h2>
      <div class="panel">
        ${buildCoverageTable(coverage)}
      </div>
    </section>

    <section class="section">
      <h2>Screenshots</h2>
      <div class="shot-grid">
        ${copy.screenshots.map(buildScreenshot).join('')}
      </div>
    </section>

    <div class="footer">
      Snapshot generated ${escapeHtml(formatTime(stats?._meta?.generated))} · refreshed ${escapeHtml(formatTime(stats?._meta?.refreshed_at))} · ${escapeHtml(copy.station_labels.join(' / '))}
    </div>
  `;
}

async function main() {
  const [copy, stats, history] = await Promise.all([
    loadJson('./data/factory-copy.json', DEFAULT_COPY),
    loadJson('./data/factory-stats.json', { recent_runs: [], open_bugs: [], _meta: {}, test_coverage: {}, factory: { cluster: { nodes: [], total_ram_gb: 0 } } }),
    loadJson('./data/factory-history.json', { rollups: [] }),
  ]);
  DATA.copy = copy;
  DATA.stats = stats;
  DATA.history = history;
  render(copy, stats, history);
}

main().catch((error) => {
  const root = document.getElementById('factory-dashboard');
  root.innerHTML = `<div class="error">Factory dashboard failed to load: ${escapeHtml(error.message)}</div>`;
});
