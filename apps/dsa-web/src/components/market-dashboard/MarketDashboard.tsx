import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  Globe2,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import {
  stocksApi,
  type MarketDashboardRankingItem,
  type MarketDashboardRegion,
  type MarketDashboardResponse,
} from '../../api/stocks';
import { getParsedApiError } from '../../api/error';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { cn } from '../../utils/cn';
import { Card, EmptyState, InlineAlert, Tooltip } from '../common';

const REFRESH_INTERVAL_MS = 60_000;

const REGION_OPTIONS: Array<{ value: MarketDashboardRegion; zh: string; en: string }> = [
  { value: 'cn', zh: '中国 A 股', en: 'China A-shares' },
  { value: 'hk', zh: '中国香港', en: 'Hong Kong' },
  { value: 'us', zh: '美国', en: 'United States' },
  { value: 'jp', zh: '日本', en: 'Japan' },
  { value: 'kr', zh: '韩国', en: 'South Korea' },
];

const COPY = {
  zh: {
    title: '全球市场驾驶舱',
    subtitle: '指数、市场宽度、板块热力与结构化观察集中在一个视图。',
    market: '市场',
    refresh: '刷新',
    refreshing: '刷新中',
    source: '项目配置的数据源降级链',
    updated: '更新',
    partial: '部分覆盖',
    stale: '陈旧数据',
    unavailable: '暂不可用',
    live: '已更新',
    backgroundRefresh: '后台刷新中',
    partialDescription: '部分数据源尚未完成，已先展示可用分块；后台刷新完成后会在下次轮询自动补齐。',
    staleDescription: '本次外部数据源刷新失败或超时，当前展示最近一次成功数据，并明确保留其更新时间。',
    unavailableStatusDescription: '当前没有可靠的成功数据。服务端已限制单次等待时间，并会继续在后台刷新。',
    unavailableTitle: '暂时无法加载市场数据',
    unavailableDescription: '检查数据源网络连接后重试；若存在最近成功数据会明确标记为陈旧，不会外推或虚构市场数据。',
    breadth: '市场宽度',
    advancers: '上涨',
    decliners: '下跌',
    flat: '平盘',
    limit: '涨停 / 跌停',
    turnover: '成交额',
    turnoverUnit: '亿元',
    indices: '主要指数',
    heatmap: '板块热力',
    sector: '行业',
    concept: '概念',
    noRanking: '当前市场的数据源暂未提供板块与概念排名。',
    observation: '市场观察',
    light: '市场信号灯',
    score: '结构分',
    fullReview: '生成完整复盘',
    coverageNote: '国际市场当前以主要指数为主；市场宽度和板块榜仅在数据源真实提供时展示。',
    dataBoundary: '数据边界',
    noIndices: '当前数据源没有返回主要指数，请稍后重试。',
    highLow: '高 / 低',
    blockIndices: '指数',
    blockBreadth: '宽度',
    blockSectors: '行业',
    blockConcepts: '概念',
  },
  en: {
    title: 'Global Market Cockpit',
    subtitle: 'Major indices, breadth, sector heat and structured observations in one view.',
    market: 'Market',
    refresh: 'Refresh',
    refreshing: 'Refreshing',
    source: 'Configured provider fallback chain',
    updated: 'Updated',
    partial: 'Partial coverage',
    stale: 'Stale data',
    unavailable: 'Unavailable',
    live: 'Updated',
    backgroundRefresh: 'Refreshing in background',
    partialDescription: 'Some providers are still pending. Available blocks are shown now and will be filled on a later poll.',
    staleDescription: 'The latest provider refresh failed or timed out. The last successful result remains visible with its timestamp.',
    unavailableStatusDescription: 'No reliable successful result is available yet. The server bounded this request and continues refreshing in the background.',
    unavailableTitle: 'Market data is temporarily unavailable',
    unavailableDescription: 'Check provider connectivity and retry. The dashboard does not invent missing market data.',
    breadth: 'Market breadth',
    advancers: 'Advancers',
    decliners: 'Decliners',
    flat: 'Flat',
    limit: 'Limit up / down',
    turnover: 'Turnover',
    turnoverUnit: '100m local',
    indices: 'Major indices',
    heatmap: 'Sector heat',
    sector: 'Industry',
    concept: 'Theme',
    noRanking: 'The current provider does not expose sector or theme rankings for this market.',
    observation: 'Market observations',
    light: 'Market Light',
    score: 'Structure score',
    fullReview: 'Generate full review',
    coverageNote: 'International views currently prioritize major indices; breadth and rankings appear only when supplied.',
    dataBoundary: 'Data boundary',
    noIndices: 'No major-index data was returned. Please retry later.',
    highLow: 'High / low',
    blockIndices: 'Indices',
    blockBreadth: 'Breadth',
    blockSectors: 'Sectors',
    blockConcepts: 'Themes',
  },
};

type MarketDashboardProps = {
  className?: string;
  onRunReview?: (region: MarketDashboardRegion) => void;
  reviewLoading?: boolean;
};

function formatNumber(value?: number | null, maximumFractionDigits = 2): string {
  if (value == null || !Number.isFinite(value)) return '--';
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits }).format(value);
}

function formatDateTime(value: string, language: 'zh' | 'en'): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value || '--';
  return new Intl.DateTimeFormat(language === 'en' ? 'en-US' : 'zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(parsed);
}

function signedPct(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return '--';
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function heatStyle(value?: number | null): React.CSSProperties {
  if (value == null || !Number.isFinite(value)) return {};
  const intensity = Math.min(0.28, 0.08 + Math.abs(value) / 30);
  return {
    backgroundColor: value >= 0
      ? `rgba(34, 197, 94, ${intensity})`
      : `rgba(244, 63, 94, ${intensity})`,
  };
}

const RankingGrid: React.FC<{
  items: Array<MarketDashboardRankingItem & { kind: string }>;
}> = ({ items }) => (
  <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 2xl:grid-cols-5">
    {items.map((item, index) => (
      <div
        key={`${item.kind}-${item.name}-${index}`}
        className="min-w-0 rounded-xl border border-white/8 bg-white/[0.025] p-3 transition-transform duration-200 hover:-translate-y-0.5 hover:border-primary/35"
        style={heatStyle(item.changePct)}
      >
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-sm font-medium text-foreground">{item.name}</span>
          <span className="rounded-full border border-white/10 px-1.5 py-0.5 text-[10px] text-secondary">{item.kind}</span>
        </div>
        <div className={cn(
          'mt-3 font-mono text-lg font-semibold',
          (item.changePct ?? 0) >= 0 ? 'text-success' : 'text-danger',
        )}>
          {signedPct(item.changePct)}
        </div>
      </div>
    ))}
  </div>
);

export const MarketDashboard: React.FC<MarketDashboardProps> = ({
  className,
  onRunReview,
  reviewLoading = false,
}) => {
  const { language } = useUiLanguage();
  const text = COPY[language];
  const [region, setRegion] = useState<MarketDashboardRegion>('cn');
  const [data, setData] = useState<MarketDashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestSequence = useRef(0);
  const inFlightRegions = useRef(new Set<MarketDashboardRegion>());
  const dataByRegion = useRef(new Map<MarketDashboardRegion, MarketDashboardResponse>());

  const load = useCallback(async (nextRegion: MarketDashboardRegion, retainData = false) => {
    if (!retainData) setData(dataByRegion.current.get(nextRegion) || null);
    // Interval, focus and manual refresh can fire together. One in-flight request
    // per market is enough; the backend also single-flights every data block.
    if (inFlightRegions.current.has(nextRegion)) return;
    inFlightRegions.current.add(nextRegion);
    const requestId = requestSequence.current + 1;
    requestSequence.current = requestId;
    setLoading(true);
    setError(null);
    try {
      const response = await stocksApi.getMarketDashboard(nextRegion);
      dataByRegion.current.set(nextRegion, response);
      if (requestSequence.current === requestId) setData(response);
    } catch (err) {
      if (requestSequence.current === requestId) setError(getParsedApiError(err).message);
    } finally {
      inFlightRegions.current.delete(nextRegion);
      if (requestSequence.current === requestId) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(region);
  }, [load, region]);

  useEffect(() => {
    const refreshWhenVisible = () => {
      if (document.visibilityState === 'visible') void load(region, true);
    };
    const intervalId = window.setInterval(refreshWhenVisible, REFRESH_INTERVAL_MS);
    window.addEventListener('focus', refreshWhenVisible);
    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener('focus', refreshWhenVisible);
    };
  }, [load, region]);

  const rankingItems = useMemo(() => {
    if (!data?.rankings.available) return [];
    return [
      ...data.rankings.topSectors.map((item) => ({ ...item, kind: text.sector })),
      ...data.rankings.bottomSectors.map((item) => ({ ...item, kind: text.sector })),
      ...data.rankings.topConcepts.map((item) => ({ ...item, kind: text.concept })),
      ...data.rankings.bottomConcepts.map((item) => ({ ...item, kind: text.concept })),
    ].sort((a, b) => Math.abs(b.changePct ?? 0) - Math.abs(a.changePct ?? 0));
  }, [data, text.concept, text.sector]);

  const status = data?.marketLight.status || 'yellow';
  const statusClass = status === 'green'
    ? 'border-success/30 bg-success/10 text-success'
    : status === 'red'
      ? 'border-danger/30 bg-danger/10 text-danger'
      : 'border-warning/30 bg-warning/10 text-warning';
  const effectiveDataStatus = data?.dataStatus || (
    data?.marketLight.dataQuality === 'ok' ? 'ok' : 'partial'
  );
  const dataStatusLabel = effectiveDataStatus === 'ok'
    ? text.live
    : effectiveDataStatus === 'stale'
      ? text.stale
      : effectiveDataStatus === 'unavailable'
        ? text.unavailable
        : text.partial;
  const blockLabels: Record<string, string> = {
    indices: text.blockIndices,
    breadth: text.blockBreadth,
    sectors: text.blockSectors,
    concepts: text.blockConcepts,
  };
  const blockStatusLabels: Record<string, string> = {
    fresh: text.live,
    stale: text.stale,
    refreshing: text.backgroundRefresh,
    unavailable: text.unavailable,
  };
  const dataStatusMessage = effectiveDataStatus === 'stale'
    ? text.staleDescription
    : effectiveDataStatus === 'unavailable'
      ? text.unavailableStatusDescription
      : effectiveDataStatus === 'partial'
        ? text.partialDescription
        : null;

  return (
    <div className={cn('space-y-3', className)} data-testid="market-dashboard">
      <Card padding="md" className="overflow-hidden">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-primary/25 bg-primary/10 text-primary">
                <Globe2 className="h-5 w-5" />
              </span>
              <div>
                <h1 className="text-lg font-semibold tracking-tight text-foreground">{text.title}</h1>
                <p className="mt-0.5 text-xs text-secondary">{text.subtitle}</p>
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 rounded-xl border border-border/70 bg-background/55 px-3 py-2 text-xs text-secondary">
              <span>{text.market}</span>
              <select
                aria-label={text.market}
                value={region}
                onChange={(event) => setRegion(event.target.value as MarketDashboardRegion)}
                className="min-w-28 bg-transparent font-medium text-foreground outline-none"
              >
                {REGION_OPTIONS.map((item) => (
                  <option key={item.value} value={item.value}>
                    {language === 'en' ? item.en : item.zh}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={() => void load(region, true)}
              disabled={loading}
              className="btn-secondary inline-flex items-center gap-2 px-3 py-2 text-xs"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
              {loading ? text.refreshing : text.refresh}
            </button>
            {onRunReview ? (
              <button
                type="button"
                onClick={() => onRunReview(region)}
                disabled={reviewLoading}
                className="btn-primary inline-flex items-center gap-2 px-3 py-2 text-xs"
              >
                <Sparkles className="h-3.5 w-3.5" />
                {text.fullReview}
              </button>
            ) : null}
          </div>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-white/7 pt-3 text-[11px] text-secondary">
          <span>{text.source}</span>
          <span>{text.updated}: {data ? formatDateTime(data.dataUpdatedAt || data.generatedAt, language) : '--'}</span>
          {data ? (
            <span className={cn(
              'rounded-full border px-2 py-0.5',
              effectiveDataStatus === 'ok'
                ? 'border-success/25 bg-success/10 text-success'
                : 'border-warning/25 bg-warning/10 text-warning',
            )}>
              {dataStatusLabel}{data.refreshing ? ` · ${text.backgroundRefresh}` : ''}
            </span>
          ) : null}
          {data ? Object.entries(data.blocks || {})
            .filter(([, block]) => block.status !== 'unsupported')
            .map(([name, block]) => (
              <Tooltip
                key={name}
                content={[
                  block.updatedAt ? `${text.updated}: ${formatDateTime(block.updatedAt, language)}` : null,
                  block.message,
                ].filter(Boolean).join(' · ') || undefined}
                focusable
              >
                <span
                  className={cn(
                    'rounded-full border px-2 py-0.5',
                    block.status === 'fresh'
                      ? 'border-white/10 text-secondary'
                      : 'border-warning/20 bg-warning/5 text-warning',
                  )}
                >
                  {blockLabels[name] || name}: {blockStatusLabels[block.status] || block.status}
                </span>
              </Tooltip>
            )) : null}
        </div>
      </Card>

      {error ? (
        <InlineAlert
          variant="warning"
          title={text.unavailableTitle}
          message={`${error} ${text.unavailableDescription}`}
          className="rounded-xl"
        />
      ) : null}

      {!error && dataStatusMessage ? (
        <InlineAlert
          variant="warning"
          title={dataStatusLabel}
          message={dataStatusMessage}
          className="rounded-xl"
        />
      ) : null}

      {!data && !loading ? (
        <EmptyState title={text.unavailableTitle} description={text.unavailableDescription} />
      ) : null}

      {data ? (
        <>
          <section className="grid grid-cols-1 gap-3 xl:grid-cols-12">
            <Card padding="md" className="xl:col-span-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-medium uppercase tracking-[0.16em] text-secondary">{text.light}</p>
                  <div className="mt-2 flex items-end gap-2">
                    <span className="font-mono text-4xl font-semibold text-foreground">{data.marketLight.score ?? '--'}</span>
                    <span className="pb-1 text-xs text-secondary">/ 100 · {text.score}</span>
                  </div>
                </div>
                <span className={cn('rounded-full border px-2.5 py-1 text-xs font-medium', statusClass)}>
                  {data.marketLight.temperatureLabel || data.marketLight.label || status}
                </span>
              </div>
              <p className="mt-4 text-sm leading-6 text-secondary-text">
                {data.marketLight.guidance || data.marketLight.label || '--'}
              </p>
            </Card>

            <Card padding="md" className="xl:col-span-8">
              <div className="mb-3 flex items-center gap-2">
                <BarChart3 className="h-4 w-4 text-primary" />
                <h2 className="text-sm font-semibold text-foreground">{text.indices}</h2>
              </div>
              {data.indices.length > 0 ? (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 2xl:grid-cols-4">
                  {data.indices.slice(0, 8).map((item) => {
                    const positive = item.changePct >= 0;
                    return (
                      <div key={item.code} className="rounded-xl border border-white/8 bg-white/[0.025] p-3 transition-colors hover:border-primary/30">
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-xs text-secondary">{item.name}</span>
                          {positive ? <ArrowUpRight className="h-4 w-4 text-success" /> : <ArrowDownRight className="h-4 w-4 text-danger" />}
                        </div>
                        <div className="mt-2 flex items-baseline justify-between gap-2">
                          <span className="font-mono text-lg font-semibold text-foreground">{formatNumber(item.current)}</span>
                          <span className={cn('font-mono text-xs font-medium', positive ? 'text-success' : 'text-danger')}>
                            {signedPct(item.changePct)}
                          </span>
                        </div>
                        <p className="mt-2 text-[10px] text-secondary">{text.highLow}: {formatNumber(item.high)} / {formatNumber(item.low)}</p>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <p className="py-8 text-center text-sm text-secondary">{text.noIndices}</p>
              )}
            </Card>
          </section>

          <section className="grid grid-cols-1 gap-3 xl:grid-cols-12">
            <Card padding="md" className="xl:col-span-4">
              <div className="mb-3 flex items-center gap-2">
                <Activity className="h-4 w-4 text-primary" />
                <h2 className="text-sm font-semibold text-foreground">{text.breadth}</h2>
              </div>
              {data.breadth.available ? (
                <div className="grid grid-cols-2 gap-2">
                  {[
                    [text.advancers, formatNumber(data.breadth.upCount, 0), 'text-success'],
                    [text.decliners, formatNumber(data.breadth.downCount, 0), 'text-danger'],
                    [text.flat, formatNumber(data.breadth.flatCount, 0), 'text-secondary-text'],
                    [text.limit, `${data.breadth.limitUpCount} / ${data.breadth.limitDownCount}`, 'text-warning'],
                  ].map(([label, value, color]) => (
                    <div key={label} className="rounded-xl border border-white/8 bg-white/[0.025] p-3">
                      <p className="text-[11px] text-secondary">{label}</p>
                      <p className={cn('mt-1 font-mono text-xl font-semibold', color)}>{value}</p>
                    </div>
                  ))}
                  <div className="col-span-2 rounded-xl border border-primary/15 bg-primary/5 p-3">
                    <p className="text-[11px] text-secondary">{text.turnover}</p>
                    <p className="mt-1 font-mono text-xl font-semibold text-foreground">
                      {formatNumber(data.breadth.totalAmount, 0)} <span className="text-xs font-normal text-secondary">{text.turnoverUnit}</span>
                    </p>
                  </div>
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-white/10 p-4 text-xs leading-5 text-secondary">
                  {text.coverageNote}
                </div>
              )}
            </Card>

            <Card padding="md" className="xl:col-span-8">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-primary" />
                  <h2 className="text-sm font-semibold text-foreground">{text.heatmap}</h2>
                </div>
                <span className="text-[10px] text-secondary">{data.tradeDate}</span>
              </div>
              {rankingItems.length > 0 ? <RankingGrid items={rankingItems} /> : (
                <div className="rounded-xl border border-dashed border-white/10 px-4 py-10 text-center text-sm text-secondary">
                  {text.noRanking}
                </div>
              )}
            </Card>
          </section>

          <Card padding="md">
            <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.45fr)]">
              <div>
                <div className="mb-3 flex items-center gap-2">
                  <ShieldCheck className="h-4 w-4 text-primary" />
                  <h2 className="text-sm font-semibold text-foreground">{text.observation}</h2>
                </div>
                <div className="grid gap-2 md:grid-cols-2">
                  {(data.marketLight.reasons || []).map((reason, index) => (
                    <div key={`${reason}-${index}`} className="flex gap-2 rounded-xl border border-white/8 bg-white/[0.025] p-3 text-xs leading-5 text-secondary-text">
                      <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                      <span>{reason}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="rounded-xl border border-warning/15 bg-warning/5 p-4">
                <p className="text-xs font-semibold text-warning">{text.dataBoundary}</p>
                <p className="mt-2 text-xs leading-5 text-secondary-text">{text.coverageNote}</p>
              </div>
            </div>
          </Card>
        </>
      ) : null}
    </div>
  );
};
