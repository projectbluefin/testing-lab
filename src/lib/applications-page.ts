import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

interface SummaryMetric {
  id: string;
  label: string;
  value: number;
  unit: string;
  state: string;
  state_reason: string | null;
  source_url: string;
  collected_at: string;
  derivation: string;
}

interface ApplicationEntry {
  id: string;
  display_name: string;
  scope: string;
  primary_suite: string;
  fallback_suites: string[];
  state: string;
  state_reason: string | null;
  source_url: string;
}

interface FallbackSignal {
  suite: string;
  matched_scenarios: string[];
  status: string;
  last_run: string | null;
  workflow_name: string | null;
  state: string;
  state_reason: string;
  source_url: string;
  collected_at: string;
  derivation: string;
}

interface ApplicationRow {
  id: string;
  app_id: string;
  variant: string;
  branch: string;
  primary_suite: string;
  primary_result_status: string;
  primary_last_run: string | null;
  scenario_total: number;
  scenario_failed: number;
  fallback_signal_count: number;
  fallback_signals: FallbackSignal[];
  state: string;
  state_reason: string;
  source_url: string;
  collected_at: string;
  derivation: string;
}

interface ApplicationsDataset {
  schema_version: string;
  _meta: {
    page: string;
    description: string;
    generated_at: string;
    starter_artifact: boolean;
    status: string;
  };
  summary_metrics: SummaryMetric[];
  applications: ApplicationEntry[];
  rows: ApplicationRow[];
}

interface EvidenceHistoryEntry {
  run_date: string;
  workflow_name: string | null;
  status: string;
  scenarios: number;
  failed: number;
}

interface ResultEvidenceFile {
  history?: EvidenceHistoryEntry[];
}

export interface ApplicationsPageModel {
  dataset: ApplicationsDataset;
  application: ApplicationEntry;
  applications: ApplicationEntry[];
  summaryMetrics: SummaryMetric[];
  summaryMetricMap: Record<string, SummaryMetric | undefined>;
  rows: Array<ApplicationRow & {
    app: ApplicationEntry;
    latestEvidenceAt: string | null;
    matchedScenarioCount: number;
    primaryEvidenceLink: string;
    fallbackEvidenceLinks: string[];
  }>;
  fallbackSignals: Array<
    FallbackSignal & {
      app: ApplicationEntry;
      variant: string;
      branch: string;
      rowId: string;
      matchedScenarioCount: number;
    }
  >;
  historyEvents: Array<{
    label: string;
    sourceKind: 'primary' | 'fallback';
    variant: string;
    branch: string;
    suite: string;
    runDate: string;
    workflowName: string | null;
    status: string;
    failed: number;
    scenarios: number;
    sourceUrl: string;
  }>;
  chartData: {
    outcomes: Array<{
      variant: string;
      branch: string;
      appId: string;
      appName: string;
      stateScore: number;
      stateLabel: string;
      primaryStatus: string;
      fallbackSignalCount: number;
      matchedScenarioCount: number;
      latestEvidenceAt: string | null;
    }>;
    fallbackDistribution: Array<{
      variant: string;
      branch: string;
      appId: string;
      appName: string;
      suite: string;
      status: string;
      signalCount: number;
      matchedScenarioCount: number;
      lastRun: string | null;
    }>;
    historySeries: Array<{
      label: string;
      sourceKind: 'primary' | 'fallback';
      runDate: string;
      failed: number;
      scenarios: number;
      status: string;
      workflowName: string | null;
      sourceUrl: string;
    }>;
  };
}

function readJson<T>(path: string): T {
  return JSON.parse(readFileSync(path, 'utf8')) as T;
}

function sourceUrlToLocalPath(repoRoot: string, sourceUrl: string): string | null {
  const marker = '/blob/main/';
  if (!sourceUrl.includes(marker)) {
    return null;
  }

  const relativePath = sourceUrl.split(marker)[1];
  return join(repoRoot, relativePath);
}

function readEvidenceHistory(repoRoot: string, sourceUrl: string): EvidenceHistoryEntry[] {
  const localPath = sourceUrlToLocalPath(repoRoot, sourceUrl);
  if (!localPath || !existsSync(localPath)) {
    return [];
  }

  const evidence = readJson<ResultEvidenceFile>(localPath);
  return Array.isArray(evidence.history) ? evidence.history : [];
}

function uniqueStrings(values: string[]) {
  return [...new Set(values)];
}

export function loadApplicationsPageModel(datasetPath: string, repoRoot: string): ApplicationsPageModel {
  const dataset = readJson<ApplicationsDataset>(datasetPath);
  const application = dataset.applications[0];
  const applicationMap = Object.fromEntries(dataset.applications.map((entry) => [entry.id, entry])) as Record<
    string,
    ApplicationEntry
  >;

  const rows = dataset.rows.map((row) => {
    const latestFallback = row.fallback_signals
      .map((signal) => signal.last_run)
      .filter((value): value is string => Boolean(value))
      .sort()
      .at(-1) ?? null;
    const latestEvidenceAt = row.primary_last_run ?? latestFallback;
    const matchedScenarioCount = row.fallback_signals.reduce(
      (total, signal) => total + signal.matched_scenarios.length,
      0,
    );

    return {
      ...row,
      app: applicationMap[row.app_id] ?? application,
      latestEvidenceAt,
      matchedScenarioCount,
      primaryEvidenceLink: row.source_url,
      fallbackEvidenceLinks: uniqueStrings(row.fallback_signals.map((signal) => signal.source_url)),
    };
  });

  const fallbackSignals = rows.flatMap((row) =>
    row.fallback_signals.map((signal) => ({
      ...signal,
      app: row.app,
      variant: row.variant,
      branch: row.branch,
      rowId: row.id,
      matchedScenarioCount: signal.matched_scenarios.length,
    })),
  );

  const historyEvents = [
    ...rows.flatMap((row) =>
      readEvidenceHistory(repoRoot, row.source_url).map((entry) => ({
        label: `${row.app.display_name} ${row.variant}/${row.branch} ${row.primary_suite} primary`,
        sourceKind: 'primary' as const,
        variant: row.variant,
        branch: row.branch,
        suite: row.primary_suite,
        runDate: entry.run_date,
        workflowName: entry.workflow_name,
        status: entry.status,
        failed: entry.failed,
        scenarios: entry.scenarios,
        sourceUrl: row.source_url,
      })),
    ),
    ...fallbackSignals.flatMap((signal) =>
      readEvidenceHistory(repoRoot, signal.source_url).map((entry) => ({
        label: `${signal.app.display_name} ${signal.variant}/${signal.branch} ${signal.suite} fallback`,
        sourceKind: 'fallback' as const,
        variant: signal.variant,
        branch: signal.branch,
        suite: signal.suite,
        runDate: entry.run_date,
        workflowName: entry.workflow_name,
        status: entry.status,
        failed: entry.failed,
        scenarios: entry.scenarios,
        sourceUrl: signal.source_url,
      })),
    ),
  ].sort((left, right) => left.runDate.localeCompare(right.runDate));

  const summaryMetricMap = Object.fromEntries(
    dataset.summary_metrics.map((metric) => [metric.id, metric]),
  ) as Record<string, SummaryMetric | undefined>;

  return {
    dataset,
    application,
    applications: dataset.applications,
    summaryMetrics: dataset.summary_metrics,
    summaryMetricMap,
    rows,
    fallbackSignals,
    historyEvents,
    chartData: {
      outcomes: rows.map((row) => ({
        variant: row.variant,
        branch: row.branch,
        appId: row.app_id,
        appName: row.app.display_name,
        stateScore:
          row.state === 'available'
            ? 2
            : row.fallback_signal_count > 0
              ? 1
              : 0,
        stateLabel:
          row.state === 'available'
            ? 'Primary evidence published'
            : row.fallback_signal_count > 0
              ? 'Fallback signal only'
              : 'No application evidence',
        primaryStatus: row.primary_result_status,
        fallbackSignalCount: row.fallback_signal_count,
        matchedScenarioCount: row.matchedScenarioCount,
        latestEvidenceAt: row.latestEvidenceAt,
      })),
      fallbackDistribution: rows.map((row) => ({
        variant: row.variant,
        branch: row.branch,
        appId: row.app_id,
        appName: row.app.display_name,
        suite: row.fallback_signals[0]?.suite ?? row.app.fallback_suites[0] ?? 'n/a',
        status: row.fallback_signals[0]?.status ?? 'none',
        signalCount: row.fallback_signal_count,
        matchedScenarioCount: row.matchedScenarioCount,
        lastRun: row.fallback_signals[0]?.last_run ?? null,
      })),
      historySeries: historyEvents.map((event) => ({
        label: event.label,
        sourceKind: event.sourceKind,
        runDate: event.runDate,
        failed: event.failed,
        scenarios: event.scenarios,
        status: event.status,
        workflowName: event.workflowName,
        sourceUrl: event.sourceUrl,
      })),
    },
  };
}
