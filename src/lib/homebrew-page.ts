import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';

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

interface TapEntry {
  id: string;
  name: string;
  url: string;
  description: string | null;
  state: string;
  state_reason: string | null;
  source_url: string;
  collected_at: string;
  derivation: string;
}

interface HomebrewRow {
  id: string;
  variant: string;
  branch: string;
  tap_name: string | null;
  tap_url: string | null;
  install_count: number | null;
  download_count: number | null;
  state: string;
  state_reason: string | null;
  source_url: string;
  collected_at: string;
  derivation: string;
}

export interface PackageLeaderboardEntry {
  id: string;
  package_name: string;
  tap_name: string | null;
  tap_url: string | null;
  install_count: number | null;
  download_count: number | null;
  state: string;
  state_reason: string | null;
  source_url: string;
  collected_at: string;
  derivation: string;
}

export interface TapDensityEntry {
  id: string;
  variant: string;
  branch: string;
  lane_label: string;
  tap_name: string | null;
  tap_url: string | null;
  package_count: number | null;
  install_count: number | null;
  download_count: number | null;
  state: string;
  state_reason: string | null;
  source_url: string;
  collected_at: string;
  derivation: string;
}

interface HomebrewDataset {
  schema_version: string;
  _meta: {
    page: string;
    description: string;
    generated_at: string;
    starter_artifact: boolean;
    status: string;
  };
  summary_metrics: SummaryMetric[];
  taps: TapEntry[];
  rows: HomebrewRow[];
  package_leaderboard?: unknown[];
  package_rows?: unknown[];
  packages?: unknown[];
  tap_density?: unknown[];
  tap_density_rows?: unknown[];
  lane_tap_density?: unknown[];
}

interface MigratedTapPackage {
  name: string;
  downloads?: number;
  installs_90d?: number;
}

interface MigratedTap {
  name: string;
  url: string;
  packages?: MigratedTapPackage[];
}

interface MigratedPackageStats {
  source_url?: string;
  generated_at?: string;
  taps?: MigratedTap[];
}

export interface HomebrewPageModel {
  dataset: HomebrewDataset;
  summaryMetrics: SummaryMetric[];
  summaryMetricMap: Record<string, SummaryMetric | undefined>;
  taps: TapEntry[];
  rows: HomebrewRow[];
  availableRows: HomebrewRow[];
  unavailableRows: HomebrewRow[];
  packageLeaderboard: PackageLeaderboardEntry[];
  tapDensityRows: TapDensityEntry[];
  tapDensitySummary: {
    lanesWithPackageDensity: number;
    lanesAwaitingPackageDensity: number;
    totalPackagesInScope: number;
    distinctTapsWithPackages: number;
    averagePackagesPerLane: number;
  };
  chartData: {
    laneStatus: Array<{
      id: string;
      label: string;
      stateScore: number;
      stateLabel: string;
      installCount: number | null;
      downloadCount: number | null;
      sourceUrl: string;
    }>;
  };
}

function readJson<T>(path: string): T {
  return JSON.parse(readFileSync(path, 'utf8')) as T;
}

function toNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function readFallbackPackageStats(datasetPath: string): MigratedPackageStats | null {
  const migratedPath = join(dirname(datasetPath), 'homebrew-package-stats-migrated.json');
  if (!existsSync(migratedPath)) return null;
  return readJson<MigratedPackageStats>(migratedPath);
}

function normalizePackageLeaderboard(
  dataset: HomebrewDataset,
  fallbackStats: MigratedPackageStats | null,
): PackageLeaderboardEntry[] {
  const rawEntries = [
    ...(Array.isArray(dataset.package_leaderboard) ? dataset.package_leaderboard : []),
    ...(Array.isArray(dataset.package_rows) ? dataset.package_rows : []),
    ...(Array.isArray(dataset.packages) ? dataset.packages : []),
  ];

  const sourceFromRows = dataset.rows.find((row) => row.state === 'available')?.source_url;
  const collectedFromRows = dataset.rows.find((row) => row.state === 'available')?.collected_at;

  const normalizedFromDataset = rawEntries
    .map((entry, index) => {
      const item = entry as Record<string, unknown>;
      const packageName =
        (typeof item.package_name === 'string' && item.package_name) ||
        (typeof item.name === 'string' && item.name) ||
        (typeof item.package === 'string' && item.package) ||
        (typeof item.formula === 'string' && item.formula) ||
        null;
      if (!packageName) return null;

      const installCount = toNumber(item.install_count ?? item.installs_90d ?? item.installs);
      const downloadCount = toNumber(item.download_count ?? item.downloads);
      const tapName =
        (typeof item.tap_name === 'string' && item.tap_name) ||
        (typeof item.tap === 'string' && item.tap) ||
        (typeof item.tapName === 'string' && item.tapName) ||
        null;
      const tapUrl =
        (typeof item.tap_url === 'string' && item.tap_url) ||
        (typeof item.tapUrl === 'string' && item.tapUrl) ||
        null;

      const state =
        (typeof item.state === 'string' && item.state) ||
        (installCount !== null || downloadCount !== null ? 'available' : 'unavailable');
      const stateReason =
        typeof item.state_reason === 'string'
          ? item.state_reason
          : state === 'unavailable'
            ? 'No package-level Homebrew analytics data is available for this package entry.'
            : null;

      return {
        id: (typeof item.id === 'string' && item.id) || `${packageName}-${index}`,
        package_name: packageName,
        tap_name: tapName,
        tap_url: tapUrl,
        install_count: installCount,
        download_count: downloadCount,
        state,
        state_reason: stateReason,
        source_url:
          (typeof item.source_url === 'string' && item.source_url) ||
          sourceFromRows ||
          fallbackStats?.source_url ||
          '',
        collected_at:
          (typeof item.collected_at === 'string' && item.collected_at) ||
          collectedFromRows ||
          fallbackStats?.generated_at ||
          dataset._meta.generated_at,
        derivation:
          (typeof item.derivation === 'string' && item.derivation) ||
          'Package-level Homebrew analytics entry loaded from docs/data/homebrew-ecosystem.json.',
      } satisfies PackageLeaderboardEntry;
    })
    .filter((entry): entry is PackageLeaderboardEntry => entry !== null);

  if (normalizedFromDataset.length > 0) {
    return normalizedFromDataset.sort((a, b) => {
      const installDiff = (b.install_count ?? -1) - (a.install_count ?? -1);
      if (installDiff !== 0) return installDiff;
      return (b.download_count ?? -1) - (a.download_count ?? -1);
    });
  }

  const fallbackEntries = (fallbackStats?.taps || []).flatMap((tap, tapIndex) =>
    (tap.packages || []).map((pkg, packageIndex) => ({
      id: `${tap.name}-${pkg.name}-${tapIndex}-${packageIndex}`,
      package_name: pkg.name,
      tap_name: tap.name,
      tap_url: tap.url,
      install_count: toNumber(pkg.installs_90d),
      download_count: toNumber(pkg.downloads),
      state: 'available',
      state_reason: null,
      source_url: fallbackStats?.source_url || sourceFromRows || '',
      collected_at: fallbackStats?.generated_at || collectedFromRows || dataset._meta.generated_at,
      derivation:
        'Fallback package-level leaderboard derived from docs/data/homebrew-package-stats-migrated.json until dense package rows are published in docs/data/homebrew-ecosystem.json.',
    })),
  );

  return fallbackEntries.sort((a, b) => {
    const installDiff = (b.install_count ?? -1) - (a.install_count ?? -1);
    if (installDiff !== 0) return installDiff;
    return (b.download_count ?? -1) - (a.download_count ?? -1);
  });
}

function normalizeTapDensityRows(
  dataset: HomebrewDataset,
  packageLeaderboard: PackageLeaderboardEntry[],
): TapDensityEntry[] {
  const rawEntries = [
    ...(Array.isArray(dataset.tap_density) ? dataset.tap_density : []),
    ...(Array.isArray(dataset.tap_density_rows) ? dataset.tap_density_rows : []),
    ...(Array.isArray(dataset.lane_tap_density) ? dataset.lane_tap_density : []),
  ];

  const fromDataset = rawEntries
    .map((entry) => {
      const item = entry as Record<string, unknown>;
      const variant = typeof item.variant === 'string' ? item.variant : null;
      const branch = typeof item.branch === 'string' ? item.branch : null;
      const laneLabel =
        (typeof item.lane_label === 'string' && item.lane_label) ||
        (variant && branch ? `${variant}/${branch}` : null);
      if (!variant || !branch || !laneLabel) return null;

      const packageCount = toNumber(item.package_count ?? item.packages_in_scope ?? item.tap_package_count);
      const installCount = toNumber(item.install_count ?? item.installs_90d ?? item.installs);
      const downloadCount = toNumber(item.download_count ?? item.downloads);
      const state =
        (typeof item.state === 'string' && item.state) ||
        (packageCount !== null ? 'available' : 'unavailable');

      return {
        id: (typeof item.id === 'string' && item.id) || `${variant}-${branch}`,
        variant,
        branch,
        lane_label: laneLabel,
        tap_name:
          (typeof item.tap_name === 'string' && item.tap_name) ||
          (typeof item.tap === 'string' && item.tap) ||
          null,
        tap_url:
          (typeof item.tap_url === 'string' && item.tap_url) ||
          (typeof item.tapUrl === 'string' && item.tapUrl) ||
          null,
        package_count: packageCount,
        install_count: installCount,
        download_count: downloadCount,
        state,
        state_reason:
          typeof item.state_reason === 'string'
            ? item.state_reason
            : state !== 'available'
              ? 'No dense package-level tap density is published for this lane.'
              : null,
        source_url:
          (typeof item.source_url === 'string' && item.source_url) ||
          dataset.rows.find((row) => row.id === `${variant}-${branch}`)?.source_url ||
          '',
        collected_at:
          (typeof item.collected_at === 'string' && item.collected_at) || dataset._meta.generated_at,
        derivation:
          (typeof item.derivation === 'string' && item.derivation) ||
          'Tap density entry loaded from docs/data/homebrew-ecosystem.json.',
      } satisfies TapDensityEntry;
    })
    .filter((entry): entry is TapDensityEntry => entry !== null);

  if (fromDataset.length > 0) return fromDataset;

  const packagesByTap = packageLeaderboard.reduce<Record<string, number>>((acc, pkg) => {
    if (!pkg.tap_name || pkg.state !== 'available') return acc;
    acc[pkg.tap_name] = (acc[pkg.tap_name] || 0) + 1;
    return acc;
  }, {});

  return dataset.rows.map((row) => {
    const packageCount = row.tap_name ? (packagesByTap[row.tap_name] ?? null) : null;
    const isAvailable = row.state === 'available' && packageCount !== null;

    return {
      id: row.id,
      variant: row.variant,
      branch: row.branch,
      lane_label: `${row.variant}/${row.branch}`,
      tap_name: row.tap_name,
      tap_url: row.tap_url,
      package_count: packageCount,
      install_count: row.install_count,
      download_count: row.download_count,
      state: isAvailable ? 'available' : 'unavailable',
      state_reason:
        isAvailable
          ? null
          : row.state_reason ||
            'Tap density unavailable until package-level analytics are published for this lane.',
      source_url: row.source_url,
      collected_at: row.collected_at,
      derivation:
        row.state === 'available'
          ? 'Tap density derived from package-level entries grouped by tap_name.'
          : row.derivation,
    };
  });
}

export function loadHomebrewPageModel(datasetPath: string): HomebrewPageModel {
  const dataset = readJson<HomebrewDataset>(datasetPath);

  const rows = dataset.rows;
  const availableRows = rows.filter((row) => row.state === 'available');
  const unavailableRows = rows.filter((row) => row.state !== 'available');

  const summaryMetricMap = Object.fromEntries(
    dataset.summary_metrics.map((metric) => [metric.id, metric]),
  ) as Record<string, SummaryMetric | undefined>;

  const fallbackStats = readFallbackPackageStats(datasetPath);
  const packageLeaderboard = normalizePackageLeaderboard(dataset, fallbackStats);
  const tapDensityRows = normalizeTapDensityRows(dataset, packageLeaderboard);

  const lanesWithPackageDensity = tapDensityRows.filter(
    (lane) => lane.state === 'available' && lane.package_count !== null,
  ).length;
  const lanesAwaitingPackageDensity = tapDensityRows.length - lanesWithPackageDensity;
  const totalPackagesInScope = packageLeaderboard.filter((pkg) => pkg.state === 'available').length;
  const distinctTapsWithPackages = new Set(
    packageLeaderboard.filter((pkg) => pkg.state === 'available' && pkg.tap_name).map((pkg) => pkg.tap_name),
  ).size;

  const chartData = {
    laneStatus: rows.map((row) => ({
      id: row.id,
      label: `${row.variant}/${row.branch}`,
      stateScore: row.state === 'available' ? (row.install_count !== null ? 2 : 1) : 0,
      stateLabel:
        row.state === 'available'
          ? row.install_count !== null
            ? 'Homebrew data available'
            : 'Lane tracked, no install data'
          : 'Awaiting Homebrew data',
      installCount: row.install_count,
      downloadCount: row.download_count,
      sourceUrl: row.source_url,
    })),
  };

  return {
    dataset,
    summaryMetrics: dataset.summary_metrics,
    summaryMetricMap,
    taps: dataset.taps,
    rows,
    availableRows,
    unavailableRows,
    packageLeaderboard,
    tapDensityRows,
    tapDensitySummary: {
      lanesWithPackageDensity,
      lanesAwaitingPackageDensity,
      totalPackagesInScope,
      distinctTapsWithPackages,
      averagePackagesPerLane:
        lanesWithPackageDensity > 0
          ? Number((totalPackagesInScope / lanesWithPackageDensity).toFixed(2))
          : 0,
    },
    chartData,
  };
}
