import type React from 'react';
import type {
  ReportDetails as ReportDetailsType,
  ReportMeta,
  ReportSummary as ReportSummaryType,
} from '../../types/analysis';
import { Badge, Button, Card, ScoreGauge } from '../common';
import { formatDateTime } from '../../utils/format';
import { getMarketPhaseSummaryLabel, getPartialBarLabel } from '../../utils/marketPhase';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import { useUiLanguage } from '../../contexts/UiLanguageContext';

interface ReportOverviewProps {
  meta: ReportMeta;
  summary: ReportSummaryType;
  details?: ReportDetailsType;
  isHistory?: boolean;
  watchlist?: {
    isInWatchlist: (code: string) => boolean;
    onToggle: (code: string) => void;
    isActioning: boolean;
    actionMessage: string | null;
  };
}

type BoardStatus = 'leading' | 'lagging';

type BoardSignal = {
  status: BoardStatus;
  changePct?: number;
};

type BoardSignalMaps = {
  sectors: Map<string, BoardSignal>;
  concepts: Map<string, BoardSignal>;
};

type PreparedBoard = {
  key: string;
  name: string;
  signal?: BoardSignal;
};

type UnknownRecord = Record<string, unknown>;

const asRecord = (value: unknown): UnknownRecord => (
  value && typeof value === 'object' && !Array.isArray(value) ? value as UnknownRecord : {}
);

const readRecordValue = (record: UnknownRecord, camelKey: string, snakeKey: string): unknown => (
  record[camelKey] ?? record[snakeKey]
);

const isGenericAnalysisSummary = (value?: string): boolean => {
  const normalized = (value || '').trim();
  return ['', '分析完成', 'Analysis completed', '분석 완료', '暂无分析摘要'].includes(normalized);
};

const formatEvidenceNumber = (value: unknown, digits = 2): string | null => {
  const parsed = coerceFiniteNumber(value);
  return parsed === undefined ? null : parsed.toFixed(digits);
};

const buildSnapshotMethodologySummary = (
  originalSummary: string,
  meta: ReportMeta,
  details?: ReportDetailsType,
): string => {
  if (!isGenericAnalysisSummary(originalSummary)) {
    return originalSummary;
  }

  const snapshot = asRecord(details?.contextSnapshot);
  const enhanced = asRecord(readRecordValue(snapshot, 'enhancedContext', 'enhanced_context'));
  const today = asRecord(enhanced.today);
  const realtime = asRecord(enhanced.realtime);
  const trend = asRecord(readRecordValue(enhanced, 'trendAnalysis', 'trend_analysis'));
  const fundamental = asRecord(readRecordValue(enhanced, 'fundamentalContext', 'fundamental_context'));
  const marketStructure = asRecord(readRecordValue(enhanced, 'marketStructureContext', 'market_structure_context'));

  const price = formatEvidenceNumber(realtime.price ?? today.close ?? meta.currentPrice);
  const change = coerceFiniteNumber(realtime.changePct ?? realtime.change_pct ?? today.pctChg ?? today.pct_chg ?? meta.changePct);
  const ma5 = formatEvidenceNumber(today.ma5);
  const ma10 = formatEvidenceNumber(today.ma10);
  const ma20 = formatEvidenceNumber(today.ma20);
  const biasMa5 = formatEvidenceNumber(readRecordValue(trend, 'biasMa5', 'bias_ma5'), 1);
  const volumeRatio = formatEvidenceNumber(realtime.volumeRatio ?? realtime.volume_ratio ?? today.volumeRatio ?? today.volume_ratio);
  const turnoverRate = formatEvidenceNumber(realtime.turnoverRate ?? realtime.turnover_rate);
  const alignment = String(readRecordValue(trend, 'maAlignment', 'ma_alignment') || trend.trendStatus || trend.trend_status || '').trim();
  const rawReasons = readRecordValue(trend, 'signalReasons', 'signal_reasons');
  const reasons = Array.isArray(rawReasons)
    ? rawReasons.filter((item): item is string => typeof item === 'string' && item.trim().length > 0).slice(0, 2)
    : [];
  const rawRisks = readRecordValue(trend, 'riskFactors', 'risk_factors');
  const risks = Array.isArray(rawRisks)
    ? rawRisks.filter((item): item is string => typeof item === 'string' && item.trim().length > 0).slice(0, 2)
    : [];

  if (!price && !alignment && reasons.length === 0 && risks.length === 0) {
    return originalSummary || '本次报告缺少可验证的核心摘要，请重新分析后再决策。';
  }

  const technicalEvidence = [
    price ? `最新价 ${price} 元${change === undefined ? '' : `，当日涨跌 ${change >= 0 ? '+' : ''}${change.toFixed(2)}%`}` : '',
    alignment,
    ma5 && ma10 && ma20 ? `MA5/10/20 为 ${ma5}/${ma10}/${ma20}` : '',
    biasMa5 ? `相对 MA5 乖离 ${biasMa5}%` : '',
    volumeRatio ? `量比 ${volumeRatio}` : '',
    turnoverRate ? `换手率 ${turnoverRate}%` : '',
  ].filter(Boolean).join('；');

  const dataBoundaries: string[] = [];
  const valuation = asRecord(fundamental.valuation);
  const valuationData = asRecord(valuation.data);
  const pe = formatEvidenceNumber(readRecordValue(valuationData, 'peRatio', 'pe_ratio'));
  const pb = formatEvidenceNumber(readRecordValue(valuationData, 'pbRatio', 'pb_ratio'));
  if (pe || pb) dataBoundaries.push(`估值快照 ${[pe && `PE ${pe}`, pb && `PB ${pb}`].filter(Boolean).join('、')}`);
  if (String(fundamental.status || '') === 'partial' || String(fundamental.status || '') === 'failed') {
    dataBoundaries.push('成长、业绩或资金字段存在缺口，不据此做确定性判断');
  }
  if (['partial', 'unknown'].includes(String(marketStructure.status || ''))) {
    dataBoundaries.push('题材强弱榜单证据不完整，板块归属仅作联动线索');
  }
  if (today.isEstimated === true || today.is_estimated === true) {
    dataBoundaries.push('当日行情含实时估算字段，收盘后应以最终日线复核');
  }

  const score = Number.isFinite(Number((details?.rawResult || {}).sentimentScore ?? (details?.rawResult || {}).sentiment_score))
    ? Number((details?.rawResult || {}).sentimentScore ?? (details?.rawResult || {}).sentiment_score)
    : null;
  const trendPrediction = String((details?.rawResult || {}).trendPrediction ?? (details?.rawResult || {}).trend_prediction ?? '').trim();
  const actionAdvice = String((details?.rawResult || {}).operationAdvice ?? (details?.rawResult || {}).operation_advice ?? '').trim();
  const conclusion = [trendPrediction || '趋势待确认', actionAdvice ? `建议${actionAdvice}` : '', score !== null ? `评分 ${score}/100` : ''].filter(Boolean).join('；');

  return [
    `【系统证据链】${conclusion}。`,
    `【技术验证】${technicalEvidence || '技术字段不完整，暂不延伸判断'}。`,
    reasons.length ? `【信号依据】${reasons.join('；')}。` : '',
    `【风险约束】${risks.length ? risks.join('；') : '未取得可验证的模型风险文本，需按止损位和确认条件执行'}。`,
    dataBoundaries.length ? `【数据边界】${dataBoundaries.join('；')}。` : '',
    '【方法与纪律】按“趋势—位置—量价—题材/基本面—风险”逐项核验；趋势向好不等于可追高，任一风险门槛未通过时应等待回踩、量能确认或重新分析。',
  ].filter(Boolean).join('\n');
};

const normalizeBoardName = (value?: string): string =>
  (value || '').trim().replace(/\s+/g, ' ');

const normalizeBoardType = (value?: string): 'sector' | 'concept' | null => {
  const normalized = (value || '').trim().toLowerCase();
  if (!normalized) {
    return null;
  }
  if (['行业', '行业板块', 'industry', 'sector'].includes(normalized)) {
    return 'sector';
  }
  if (['概念', '概念板块', '题材', 'concept', 'theme'].includes(normalized)) {
    return 'concept';
  }
  return null;
};

const coerceFiniteNumber = (value: unknown): number | undefined => {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : undefined;
  }
  if (typeof value === 'string') {
    const trimmed = value.trim().replace(/%$/, '');
    if (!trimmed) {
      return undefined;
    }
    const parsed = Number(trimmed);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
};

const buildRankingSignalMap = (rankings?: ReportDetailsType['sectorRankings']): Map<string, BoardSignal> => {
  const signalMap = new Map<string, BoardSignal>();
  const topBoards = Array.isArray(rankings?.top) ? rankings.top : [];
  const bottomBoards = Array.isArray(rankings?.bottom) ? rankings.bottom : [];

  topBoards.forEach((item) => {
    const normalizedName = normalizeBoardName(item?.name);
    const changePct = coerceFiniteNumber(item?.changePct);
    if (!normalizedName || changePct === undefined) {
      return;
    }
    signalMap.set(normalizedName, {
      status: 'leading',
      changePct,
    });
  });

  bottomBoards.forEach((item) => {
    const normalizedName = normalizeBoardName(item?.name);
    const changePct = coerceFiniteNumber(item?.changePct);
    if (!normalizedName || changePct === undefined) {
      return;
    }
    signalMap.set(normalizedName, {
      status: 'lagging',
      changePct,
    });
  });

  return signalMap;
};

const buildBoardSignalMaps = (details?: ReportDetailsType): BoardSignalMaps => ({
  sectors: buildRankingSignalMap(details?.sectorRankings),
  concepts: buildRankingSignalMap(details?.conceptRankings),
});

const resolveBoardSignal = (
  board: { name?: string; type?: string },
  signalMaps: BoardSignalMaps,
): BoardSignal | undefined => {
  const boardName = normalizeBoardName(board.name);
  if (!boardName) {
    return undefined;
  }
  const boardType = normalizeBoardType(board.type);
  if (boardType === 'sector') {
    return signalMaps.sectors.get(boardName);
  }
  if (boardType === 'concept') {
    return signalMaps.concepts.get(boardName);
  }
  const sectorSignal = signalMaps.sectors.get(boardName);
  const conceptSignal = signalMaps.concepts.get(boardName);
  if (sectorSignal && !conceptSignal) {
    return sectorSignal;
  }
  if (conceptSignal && !sectorSignal) {
    return conceptSignal;
  }
  return undefined;
};

const buildPreparedRelatedBoards = (
  boards: ReportDetailsType['belongBoards'],
  signalMaps: BoardSignalMaps,
): PreparedBoard[] => {
  if (!Array.isArray(boards)) {
    return [];
  }

  return boards.reduce<PreparedBoard[]>((preparedBoards, board, index) => {
    const boardName = normalizeBoardName(board?.name);
    if (!boardName) {
      return preparedBoards;
    }
    preparedBoards.push({
      key: `${boardName}-${board?.code || index}`,
      name: boardName,
      signal: resolveBoardSignal(board, signalMaps),
    });
    return preparedBoards;
  }, []);
};

/**
 * 报告概览区组件 - 终端风格
 */
export const ReportOverview: React.FC<ReportOverviewProps> = ({
  meta,
  summary,
  details,
  watchlist,
}) => {
  const { t } = useUiLanguage();
  const reportLanguage = normalizeReportLanguage(meta.reportLanguage);
  const text = getReportText(reportLanguage);
  const marketPhaseLabel = getMarketPhaseSummaryLabel(meta.marketPhaseSummary, reportLanguage);
  const partialBarLabel = meta.marketPhaseSummary?.isPartialBar === true
    ? getPartialBarLabel(reportLanguage)
    : null;
  const relatedBoards = (Array.isArray(details?.belongBoards) ? details.belongBoards : [])
    .filter((board) => normalizeBoardName(board?.name).length > 0);
  const boardSignals = buildBoardSignalMaps(details);
  const preparedRelatedBoards = buildPreparedRelatedBoards(relatedBoards, boardSignals);
  const coreInsight = buildSnapshotMethodologySummary(summary.analysisSummary, meta, details);

  const getPriceChangeStyle = (changePct: number | undefined): React.CSSProperties | undefined => {
    if (changePct === undefined || changePct === null) {
      return undefined;
    }

    if (changePct > 0) {
      return { color: 'var(--home-price-up)' };
    }

    if (changePct < 0) {
      return { color: 'var(--home-price-down)' };
    }

    return undefined;
  };

  const formatChangePct = (changePct: number | undefined): string => {
    if (changePct === undefined || changePct === null) return '--';
    const sign = changePct > 0 ? '+' : '';
    return `${sign}${changePct.toFixed(2)}%`;
  };

  const getBoardStatusLabel = (status: BoardStatus): string => {
    if (status === 'leading') {
      return text.leadingBoard;
    }
    return text.laggingBoard;
  };

  const getBoardStatusVariant = (status: BoardStatus): 'success' | 'danger' => {
    if (status === 'leading') {
      return 'success';
    }
    return 'danger';
  };

  const renderBoardChip = (board: PreparedBoard) => (
    <div
      key={board.key}
      className="inline-flex shrink-0 items-center gap-2 text-sm"
    >
      <span className="home-accent-chip px-2 py-0.5 text-xs font-medium">
        {board.name}
      </span>
      {board.signal && (
        <Badge
          variant={getBoardStatusVariant(board.signal.status)}
          className="home-board-status-badge shadow-none"
        >
          {getBoardStatusLabel(board.signal.status)}
        </Badge>
      )}
      {board.signal && board.signal.changePct !== undefined && board.signal.changePct !== null && (
        <span
          className="text-xs font-mono"
          style={getPriceChangeStyle(board.signal.changePct)}
        >
          {formatChangePct(board.signal.changePct)}
        </span>
      )}
    </div>
  );

  return (
    <div className="space-y-5">
      {/* 主信息区 - 两列布局 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 items-start">
        {/* 左侧：股票信息与结论 */}
        <div className="lg:col-span-2 space-y-5">
          {/* 股票头部 */}
          <Card variant="gradient" padding="md" className="home-report-hero">
            <div className="flex items-start justify-between mb-5">
              <div className="flex-1">
                <div className="flex items-center gap-3">
                  <h2 className="text-[28px] font-bold leading-tight text-foreground">
                    {meta.stockName || meta.stockCode}
                  </h2>
                  {/* 价格和涨跌幅 */}
                  {meta.currentPrice != null && (
                    <div className="flex items-baseline gap-2">
                      <span className="text-xl font-bold font-mono" style={getPriceChangeStyle(meta.changePct)}>
                        {meta.currentPrice.toFixed(2)}
                      </span>
                      <span className="text-sm font-semibold font-mono" style={getPriceChangeStyle(meta.changePct)}>
                        {formatChangePct(meta.changePct)}
                      </span>
                    </div>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-2 mt-1.5">
                  <span className="home-accent-chip px-2 py-0.5 font-mono text-xs">
                    {meta.stockCode}
                  </span>
                  {marketPhaseLabel ? (
                    <Badge variant="info" className="shrink-0 gap-1.5 shadow-none" aria-label={marketPhaseLabel}>
                      {marketPhaseLabel}
                    </Badge>
                  ) : null}
                  {partialBarLabel ? (
                    <Badge variant="warning" className="shrink-0 shadow-none" aria-label={partialBarLabel}>
                      {partialBarLabel}
                    </Badge>
                  ) : null}
                  <span className="text-xs text-muted-text flex items-center gap-1">
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                    </svg>
                    {formatDateTime(meta.createdAt)}
                  </span>
                </div>
              </div>
            </div>

            {/* 关键结论 */}
            <div className="home-divider border-t pt-5">
              <span className="label-uppercase">{text.keyInsights}</span>
              <p className="mt-2 max-w-[62ch] whitespace-pre-wrap text-left text-[15px] leading-7 text-foreground">
                {coreInsight || text.noAnalysisSummary}
              </p>
            </div>
          </Card>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
            {/* 操作建议 */}
            <Card
              variant="bordered"
              padding="sm"
              hoverable
              className="home-panel-card home-insight-card"
              style={{ ['--home-insight-tone' as string]: 'var(--home-strategy-buy)' }}
            >
              <div className="flex items-start gap-3">
                <div className="home-insight-icon w-8 h-8 rounded-lg bg-success/10 flex items-center justify-center flex-shrink-0">
                  <svg className="w-4 h-4 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                  </svg>
                </div>
                <div className="space-y-1.5">
                  <h4 className="home-insight-title text-[11px] font-medium uppercase tracking-[0.16em]">{text.actionAdvice}</h4>
                  <p className="home-insight-body text-sm leading-6">
                    {summary.operationAdvice || text.noAdvice}
                  </p>
                </div>
              </div>
            </Card>

            {/* 趋势预测 */}
            <Card
              variant="bordered"
              padding="sm"
              hoverable
              className="home-panel-card home-insight-card"
              style={{ ['--home-insight-tone' as string]: 'var(--home-strategy-take)' }}
            >
              <div className="flex items-start gap-3">
                <div className="home-insight-icon w-8 h-8 rounded-lg bg-warning/10 flex items-center justify-center flex-shrink-0">
                  <svg className="w-4 h-4 text-warning" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
                  </svg>
                </div>
                <div className="space-y-1.5">
                  <h4 className="home-insight-title text-[11px] font-medium uppercase tracking-[0.16em]">{text.trendPrediction}</h4>
                  <p className="home-insight-body text-sm leading-6">
                    {summary.trendPrediction || text.noPrediction}
                  </p>
                </div>
              </div>
            </Card>
          </div>

          {preparedRelatedBoards.length > 0 && (
            <Card variant="bordered" padding="sm" className="home-panel-card min-w-0 max-w-full text-left">
              <section aria-label={text.relatedBoards} className="min-w-0 max-w-full">
                <div className="mb-3 flex min-w-0 items-baseline gap-2">
                  <span className="label-uppercase">{text.boardLinkage}</span>
                  <h3 className="mt-0.5 text-base font-semibold text-foreground">{text.relatedBoards}</h3>
                </div>

                <div className="home-related-board-list flex min-h-6 w-full min-w-0 max-w-full flex-nowrap items-center gap-2 overflow-x-auto overscroll-x-contain touch-pan-x pb-1">
                  {preparedRelatedBoards.map(renderBoardChip)}
                </div>
              </section>
            </Card>
          )}
        </div>

        {/* 右侧：情绪指标 / 自选操作 */}
        <div className="flex flex-col space-y-4">
          {watchlist && meta.reportType !== 'market_review' && (
            <Card variant="bordered" padding="sm" className="home-panel-card">
              <div className="text-center space-y-3">
                <span className="label-uppercase">{t('report.watchlist')}</span>
                <div className="text-xs text-muted-text font-mono">{meta.stockCode}</div>
                <Button
                  variant={watchlist.isInWatchlist(meta.stockCode) ? 'danger-subtle' : 'secondary'}
                  size="sm"
                  isLoading={watchlist.isActioning}
                  onClick={() => watchlist.onToggle(meta.stockCode)}
                  className="w-full text-xs"
                >
                  {watchlist.isInWatchlist(meta.stockCode) ? t('report.removeFromWatchlist') : t('report.addToWatchlist')}
                </Button>
                {watchlist.actionMessage && (
                  <p className="text-[11px] text-secondary-text animate-in fade-in">{watchlist.actionMessage}</p>
                )}
              </div>
            </Card>
          )}
          <Card variant="bordered" padding="md" className="home-panel-card home-rail-card !overflow-visible">
            <div className="text-center">
              <h3 className="mb-5 text-sm font-medium tracking-wide text-foreground">{text.marketSentiment}</h3>
              <ScoreGauge score={summary.sentimentScore} size="lg" language={reportLanguage} />
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
};
