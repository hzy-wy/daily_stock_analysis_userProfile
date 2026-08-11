import type React from 'react';
import {
  PolarAngleAxis,
  PolarGrid,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from 'recharts';
import { Activity, Info } from 'lucide-react';
import type {
  PortfolioTraderProfileDimension,
  PortfolioTraderProfileDimensionKey,
  PortfolioTraderProfileResponse,
} from '../../types/portfolio';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { Badge, Card, InlineAlert } from '../common';

const DIMENSION_COPY: Record<PortfolioTraderProfileDimensionKey, { zh: string; en: string }> = {
  activity: { zh: '交易活跃度', en: 'Activity' },
  short_horizon: { zh: '短线倾向', en: 'Short horizon' },
  concentration: { zh: '集中偏好', en: 'Concentration' },
  scale_in: { zh: '加仓倾向', en: 'Scaling in' },
  profit_taking: { zh: '止盈兑现', en: 'Profit taking' },
  sizing_consistency: { zh: '尺度一致性', en: 'Sizing consistency' },
};

const ARCHETYPE_COPY: Record<string, { zh: string; en: string }> = {
  forming: { zh: '画像形成中', en: 'Profile forming' },
  active_short_term: { zh: '活跃短线型', en: 'Active short-horizon' },
  concentrated_builder: { zh: '集中加仓型', en: 'Concentrated builder' },
  patient_holder: { zh: '耐心持有型', en: 'Patient holder' },
  systematic_balanced: { zh: '尺度稳定型', en: 'Consistent sizing' },
  adaptive_balanced: { zh: '动态均衡型', en: 'Adaptive balanced' },
};

type TraderStyleProfileCardProps = {
  profile: PortfolioTraderProfileResponse | null;
  loading?: boolean;
  warning?: string | null;
};

function dimensionEvidence(
  dimension: PortfolioTraderProfileDimension,
  language: 'zh' | 'en',
): string {
  const evidence = dimension.evidence || {};
  const value = (key: string) => {
    const raw = evidence[key];
    return typeof raw === 'number' && Number.isFinite(raw) ? raw : null;
  };
  if (dimension.key === 'activity') {
    const rate = value('tradesPer30d');
    return rate == null ? '--' : language === 'en' ? `${rate.toFixed(1)} trades / 30d` : `每 30 天 ${rate.toFixed(1)} 笔`;
  }
  if (dimension.key === 'short_horizon') {
    const days = value('medianHoldingDays');
    return days == null ? '--' : language === 'en' ? `Median ${days.toFixed(0)} days` : `持有期中位数 ${days.toFixed(0)} 天`;
  }
  if (dimension.key === 'concentration') {
    const weight = value('topWeightPct');
    return weight == null ? '--' : language === 'en' ? `Top holding ${weight.toFixed(1)}%` : `第一大持仓 ${weight.toFixed(1)}%`;
  }
  if (dimension.key === 'scale_in') {
    const ratio = value('scaleInRatioPct');
    return ratio == null ? '--' : language === 'en' ? `${ratio.toFixed(1)}% add-on buys` : `加仓买入占比 ${ratio.toFixed(1)}%`;
  }
  if (dimension.key === 'profit_taking') {
    const ratio = value('profitableSellRatioPct');
    return ratio == null ? '--' : language === 'en' ? `${ratio.toFixed(1)}% profitable exits` : `盈利卖出占比 ${ratio.toFixed(1)}%`;
  }
  const cv = value('tradeSizeCv');
  return cv == null ? '--' : language === 'en' ? `Trade-size CV ${cv.toFixed(2)}` : `交易金额变异系数 ${cv.toFixed(2)}`;
}

export const TraderStyleProfileCard: React.FC<TraderStyleProfileCardProps> = ({
  profile,
  loading = false,
  warning,
}) => {
  const { language } = useUiLanguage();
  const chartData = (profile?.dimensions || []).map((dimension) => ({
    key: dimension.key,
    label: DIMENSION_COPY[dimension.key][language],
    score: dimension.available ? dimension.score : undefined,
  }));
  const archetype = profile
    ? (ARCHETYPE_COPY[profile.archetype] || ARCHETYPE_COPY.adaptive_balanced)[language]
    : ARCHETYPE_COPY.forming[language];
  const confidenceLabel = language === 'en'
    ? `${profile?.confidence || 'low'} confidence`
    : `${profile?.confidence === 'high' ? '高' : profile?.confidence === 'medium' ? '中' : '低'}置信度`;

  return (
    <Card padding="md" data-testid="trader-style-profile">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-2.5">
          <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-primary/25 bg-primary/10 text-primary">
            <Activity className="h-4.5 w-4.5" />
          </span>
          <div>
            <h2 className="text-sm font-semibold text-foreground">
              {language === 'en' ? 'Dynamic trader-style profile' : '动态交易风格画像'}
            </h2>
            <p className="mt-1 text-xs leading-5 text-secondary">
              {language === 'en'
                ? 'Derived from the selected account ledger and current holdings; higher values mean stronger tendencies, not better skill.'
                : '基于当前账户的完整交易账本与持仓生成；数值越高仅表示倾向越强，不代表能力越高。'}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={profile?.status === 'ready' ? 'success' : 'warning'}>{archetype}</Badge>
          <Badge variant="default">{confidenceLabel} · {profile?.confidenceScore ?? 0}</Badge>
        </div>
      </div>

      {warning ? (
        <InlineAlert variant="warning" message={warning} className="mt-3 rounded-xl px-3 py-2 text-xs shadow-none" />
      ) : null}

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(320px,0.85fr)_minmax(0,1.15fr)]">
        <div className="relative min-h-[300px] rounded-2xl border border-white/8 bg-white/[0.02] p-2">
          {loading ? (
            <div className="absolute inset-0 z-10 flex items-center justify-center rounded-2xl bg-background/55 backdrop-blur-sm">
              <span className="inline-flex items-center gap-2 text-xs text-secondary">
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-primary/25 border-t-primary" />
                {language === 'en' ? 'Rebuilding profile…' : '正在重建画像…'}
              </span>
            </div>
          ) : null}
          <ResponsiveContainer width="100%" height={290}>
            <RadarChart data={chartData} outerRadius="68%">
              <PolarGrid stroke="rgba(148, 163, 184, 0.24)" />
              <PolarAngleAxis dataKey="label" tick={{ fill: 'hsl(var(--secondary-text))', fontSize: 11 }} />
              <Tooltip formatter={(value) => [`${Number(value).toFixed(0)} / 100`, language === 'en' ? 'Tendency' : '倾向']} />
              <Radar dataKey="score" stroke="hsl(var(--primary))" fill="hsl(var(--primary))" fillOpacity={0.26} strokeWidth={2} connectNulls={false} />
            </RadarChart>
          </ResponsiveContainer>
          {profile?.status === 'forming' ? (
            <div className="pointer-events-none absolute inset-x-4 bottom-3 rounded-lg border border-warning/20 bg-warning/10 px-3 py-2 text-center text-[11px] text-warning">
              {language === 'en' ? 'Early profile — more observations are required.' : '早期画像：需要更多交易与观察时间后再稳定解读。'}
            </div>
          ) : null}
        </div>

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              [language === 'en' ? 'Trades' : '交易笔数', profile?.sample.tradeCount ?? 0],
              [language === 'en' ? 'Window' : '观察天数', profile?.sample.observationDays ?? 0],
              [language === 'en' ? 'Symbols' : '交易标的', profile?.sample.uniqueSymbols ?? 0],
              [language === 'en' ? 'Buys / sells' : '买入 / 卖出', `${profile?.sample.buyCount ?? 0} / ${profile?.sample.sellCount ?? 0}`],
            ].map(([label, value]) => (
              <div key={label} className="rounded-xl border border-white/8 bg-white/[0.025] p-3">
                <p className="text-[10px] uppercase tracking-wide text-secondary">{label}</p>
                <p className="mt-1 font-mono text-lg font-semibold text-foreground">{value}</p>
              </div>
            ))}
          </div>

          <div className="grid gap-2 sm:grid-cols-2">
            {(profile?.dimensions || []).map((dimension) => (
              <div key={dimension.key} className="rounded-xl border border-white/8 bg-white/[0.025] p-3">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-xs font-medium text-foreground">{DIMENSION_COPY[dimension.key][language]}</span>
                  <span className="font-mono text-sm font-semibold text-primary">
                    {dimension.available ? dimension.score : '--'}
                  </span>
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/7">
                  <div className="h-full rounded-full bg-primary transition-[width] duration-500" style={{ width: `${dimension.score ?? 0}%` }} />
                </div>
                <p className="mt-2 text-[10px] text-secondary">{dimensionEvidence(dimension, language)}</p>
              </div>
            ))}
          </div>

          <div className="flex gap-2 rounded-xl border border-primary/12 bg-primary/5 p-3 text-[11px] leading-5 text-secondary-text">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
            <span>
              {language === 'en'
                ? 'The profile updates after trades or account changes. Profit-taking uses FIFO-matched exits; missing prior buys reduce confidence.'
                : '画像会随交易和账户切换更新。止盈倾向按 FIFO 匹配卖出计算；若缺少历史买入记录，置信度会下降。'}
            </span>
          </div>
        </div>
      </div>
    </Card>
  );
};
