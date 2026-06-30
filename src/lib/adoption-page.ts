import { readFileSync } from 'node:fs';

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

interface TrustCard {
  variant: string;
  publisher_repo: string | null;
  org: string | null;
  emits_sbom: boolean;
  emits_cve_scan: boolean;
  emits_cosign_attestation: boolean;
  state: string;
  state_reason: string | null;
  source_url: string;
  collected_at: string;
  derivation: string;
}

interface AdoptionRow {
  id: string;
  variant: string;
  branch: string;
  pull_count: number | null;
  countme_active_devices: number | null;
  state: string;
  state_reason: string;
  source_url: string;
  collected_at: string;
  derivation: string;
}

interface AdoptionDataset {
  schema_version: string;
  _meta: {
    page: string;
    description: string;
    generated_at: string;
    starter_artifact: boolean;
    status: string;
  };
  summary_metrics: SummaryMetric[];
  trust_cards: TrustCard[];
  rows: AdoptionRow[];
  countme_trend?: {
    monthly: Array<{
      week_start: string;
      week_end: string;
      distros: Record<string, number>;
      total: number;
    }>;
    weekly: Array<{
      week_start: string;
      week_end: string;
      distros: Record<string, number>;
      total: number;
    }>;
    DISTROS: string[];
    LABELS: string[];
  };
  quay_trend?: Array<{
    date: string;
    count: number;
  }>;
  dora_comparison?: {
    labels: string[];
    datasets: Array<{
      label: string;
      color: string;
      values: number[];
    }>;
  };
  os_version?: {
    labels: string[];
    values: number[];
    total: number;
  };
  openssf_scorecard?: Array<{
    repo: string;
    score: string;
    date: string | null;
    indexed: boolean;
  }>;
  oci_best_practices?: Array<{
    image: string;
    cosign: string;
    sbom: string;
    zstd: string;
    chunked: string;
    slsa: string;
  }>;
}

export interface AdoptionPageModel {
  dataset: AdoptionDataset;
  summaryMetrics: SummaryMetric[];
  summaryMetricMap: Record<string, SummaryMetric | undefined>;
  trustCards: TrustCard[];
  rows: AdoptionRow[];
  /** Counts derived from rows — single source of truth for prose and metadata DL. */
  laneStats: {
    total: number;
    withPullData: number;
    withCountmeData: number;
    available: number;
    unavailable: number;
    withoutPullData: number;
    withoutCountmeData: number;
  };
  chartData: {
    lanesCoverage: Array<{
      id: string;
      label: string;
      hasPullData: boolean;
      hasCountmeData: boolean;
      state: string;
    }>;
    trustCoverage: Array<{
      variant: string;
      org: string | null;
      sbom: number;
      cveScan: number;
      cosign: number;
      state: string;
    }>;
  };
}

function readJson<T>(filePath: string): T {
  return JSON.parse(readFileSync(filePath, 'utf8')) as T;
}

export function loadAdoptionPageModel(datasetPath: string): AdoptionPageModel {
  const dataset = readJson<AdoptionDataset>(datasetPath);

  const summaryMetricMap = Object.fromEntries(
    dataset.summary_metrics.map((metric) => [metric.id, metric]),
  ) as Record<string, SummaryMetric | undefined>;

  const withPullData = dataset.rows.filter((r) => r.pull_count !== null).length;
  const withCountmeData = dataset.rows.filter((r) => r.countme_active_devices !== null).length;
  const available = dataset.rows.filter((r) => r.state === 'available').length;
  const unavailable = dataset.rows.filter((r) => r.state === 'unavailable').length;

  const laneStats = {
    total: dataset.rows.length,
    withPullData,
    withCountmeData,
    available,
    unavailable,
    withoutPullData: dataset.rows.length - withPullData,
    withoutCountmeData: dataset.rows.length - withCountmeData,
  };

  const lanesCoverage = dataset.rows.map((row) => ({
    id: row.id,
    label: `${row.variant}/${row.branch}`,
    hasPullData: row.pull_count !== null,
    hasCountmeData: row.countme_active_devices !== null,
    pullCount: row.pull_count,
    countmeActiveDevices: row.countme_active_devices,
    state: row.state,
  }));

  const trustCoverage = dataset.trust_cards.map((card) => ({
    variant: card.variant,
    org: card.org,
    sbom: card.emits_sbom ? 1 : 0,
    cveScan: card.emits_cve_scan ? 1 : 0,
    cosign: card.emits_cosign_attestation ? 1 : 0,
    state: card.state,
  }));

  return {
    dataset,
    summaryMetrics: dataset.summary_metrics,
    summaryMetricMap,
    trustCards: dataset.trust_cards,
    rows: dataset.rows,
    laneStats,
    chartData: {
      lanesCoverage,
      trustCoverage,
    },
  };
}
