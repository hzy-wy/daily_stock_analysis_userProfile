import apiClient from './index';

export type ExtractItem = {
  code?: string | null;
  name?: string | null;
  confidence: string;
};

export type ExtractFromImageResponse = {
  codes: string[];
  items?: ExtractItem[];
  rawText?: string;
};

export type MarketDashboardRegion = 'cn' | 'hk' | 'us' | 'jp' | 'kr';

export type MarketDashboardIndex = {
  code: string;
  name: string;
  current: number;
  change: number;
  changePct: number;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  prevClose?: number | null;
  volume?: number | null;
  amount?: number | null;
  amplitude?: number | null;
};

export type MarketDashboardRankingItem = {
  name: string;
  changePct?: number | null;
  source?: string | null;
};

export type MarketDashboardBlockStatus = {
  status: 'fresh' | 'stale' | 'refreshing' | 'unavailable' | 'unsupported';
  updatedAt?: string | null;
  ageSeconds?: number | null;
  message?: string | null;
};

export type MarketDashboardResponse = {
  region: MarketDashboardRegion;
  tradeDate: string;
  generatedAt: string;
  dataUpdatedAt?: string | null;
  dataStatus: 'ok' | 'partial' | 'stale' | 'unavailable';
  isStale: boolean;
  refreshing: boolean;
  blocks: Record<string, MarketDashboardBlockStatus>;
  indices: MarketDashboardIndex[];
  breadth: {
    available: boolean;
    upCount: number;
    downCount: number;
    flatCount: number;
    limitUpCount: number;
    limitDownCount: number;
    totalAmount: number;
  };
  rankings: {
    available: boolean;
    topSectors: MarketDashboardRankingItem[];
    bottomSectors: MarketDashboardRankingItem[];
    topConcepts: MarketDashboardRankingItem[];
    bottomConcepts: MarketDashboardRankingItem[];
  };
  marketLight: {
    status?: 'green' | 'yellow' | 'red';
    score?: number;
    label?: string;
    temperatureLabel?: string;
    reasons?: string[];
    guidance?: string;
    dataQuality?: 'ok' | 'partial' | 'unavailable';
  };
  coverage: Record<string, boolean>;
  sourceLabel: string;
};

function toMarketDashboardResponse(data: Record<string, unknown>): MarketDashboardResponse {
  const breadth = (data.breadth || {}) as Record<string, unknown>;
  const rankings = (data.rankings || {}) as Record<string, unknown>;
  const light = (data.market_light || {}) as Record<string, unknown>;
  const rawBlocks = (data.blocks || {}) as Record<string, unknown>;
  const blocks = Object.fromEntries(
    Object.entries(rawBlocks).map(([name, value]) => {
      const row = (value || {}) as Record<string, unknown>;
      return [name, {
        status: String(row.status || 'unavailable') as MarketDashboardBlockStatus['status'],
        updatedAt: row.updated_at == null ? null : String(row.updated_at),
        ageSeconds: row.age_seconds == null ? null : Number(row.age_seconds),
        message: row.message == null ? null : String(row.message),
      }];
    }),
  ) as Record<string, MarketDashboardBlockStatus>;
  const mapRanking = (items: unknown): MarketDashboardRankingItem[] => (
    Array.isArray(items)
      ? items.map((item) => {
          const row = item as Record<string, unknown>;
          return {
            name: String(row.name || ''),
            changePct: row.change_pct == null ? null : Number(row.change_pct),
            source: row.source == null ? null : String(row.source),
          };
        })
      : []
  );
  return {
    region: String(data.region || 'cn') as MarketDashboardRegion,
    tradeDate: String(data.trade_date || ''),
    generatedAt: String(data.generated_at || ''),
    dataUpdatedAt: data.data_updated_at == null ? null : String(data.data_updated_at),
    dataStatus: String(data.data_status || 'unavailable') as MarketDashboardResponse['dataStatus'],
    isStale: Boolean(data.is_stale),
    refreshing: Boolean(data.refreshing),
    blocks,
    indices: Array.isArray(data.indices)
      ? data.indices.map((item) => {
          const row = item as Record<string, unknown>;
          return {
            code: String(row.code || ''),
            name: String(row.name || ''),
            current: Number(row.current || 0),
            change: Number(row.change || 0),
            changePct: Number(row.change_pct || 0),
            open: row.open == null ? null : Number(row.open),
            high: row.high == null ? null : Number(row.high),
            low: row.low == null ? null : Number(row.low),
            prevClose: row.prev_close == null ? null : Number(row.prev_close),
            volume: row.volume == null ? null : Number(row.volume),
            amount: row.amount == null ? null : Number(row.amount),
            amplitude: row.amplitude == null ? null : Number(row.amplitude),
          };
        })
      : [],
    breadth: {
      available: Boolean(breadth.available),
      upCount: Number(breadth.up_count || 0),
      downCount: Number(breadth.down_count || 0),
      flatCount: Number(breadth.flat_count || 0),
      limitUpCount: Number(breadth.limit_up_count || 0),
      limitDownCount: Number(breadth.limit_down_count || 0),
      totalAmount: Number(breadth.total_amount || 0),
    },
    rankings: {
      available: Boolean(rankings.available),
      topSectors: mapRanking(rankings.top_sectors),
      bottomSectors: mapRanking(rankings.bottom_sectors),
      topConcepts: mapRanking(rankings.top_concepts),
      bottomConcepts: mapRanking(rankings.bottom_concepts),
    },
    marketLight: {
      status: light.status as MarketDashboardResponse['marketLight']['status'],
      score: light.score == null ? undefined : Number(light.score),
      label: light.label == null ? undefined : String(light.label),
      temperatureLabel: light.temperature_label == null ? undefined : String(light.temperature_label),
      reasons: Array.isArray(light.reasons) ? light.reasons.map(String) : [],
      guidance: light.guidance == null ? undefined : String(light.guidance),
      dataQuality: light.data_quality as MarketDashboardResponse['marketLight']['dataQuality'],
    },
    coverage: (data.coverage || {}) as Record<string, boolean>,
    sourceLabel: String(data.source_label || ''),
  };
}

export const stocksApi = {
  async getMarketDashboard(region: MarketDashboardRegion = 'cn'): Promise<MarketDashboardResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/stocks/market-dashboard', {
      params: { region },
      timeout: 30000,
    });
    return toMarketDashboardResponse(response.data);
  },

  async extractFromImage(file: File): Promise<ExtractFromImageResponse> {
    const formData = new FormData();
    formData.append('file', file);

    const headers: { [key: string]: string | undefined } = { 'Content-Type': undefined };
    const response = await apiClient.post(
      '/api/v1/stocks/extract-from-image',
      formData,
      {
        headers,
        timeout: 60000, // Vision API can be slow; 60s
      },
    );

    const data = response.data as { codes?: string[]; items?: ExtractItem[]; raw_text?: string };
    return {
      codes: data.codes ?? [],
      items: data.items,
      rawText: data.raw_text,
    };
  },

  async parseImport(file?: File, text?: string): Promise<ExtractFromImageResponse> {
    if (file) {
      const formData = new FormData();
      formData.append('file', file);
      const headers: { [key: string]: string | undefined } = { 'Content-Type': undefined };
      const response = await apiClient.post('/api/v1/stocks/parse-import', formData, { headers });
      const data = response.data as { codes?: string[]; items?: ExtractItem[] };
      return { codes: data.codes ?? [], items: data.items };
    }
    if (text) {
      const response = await apiClient.post('/api/v1/stocks/parse-import', { text });
      const data = response.data as { codes?: string[]; items?: ExtractItem[] };
      return { codes: data.codes ?? [], items: data.items };
    }
    throw new Error('请提供文件或粘贴文本');
  },
};
