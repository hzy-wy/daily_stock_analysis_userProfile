import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';
import { MarketDashboard } from '../MarketDashboard';

const { getMarketDashboard } = vi.hoisted(() => ({
  getMarketDashboard: vi.fn(),
}));

vi.mock('../../../api/stocks', async () => {
  const actual = await vi.importActual<typeof import('../../../api/stocks')>('../../../api/stocks');
  return {
    ...actual,
    stocksApi: { getMarketDashboard },
  };
});

function makeDashboard(region: 'cn' | 'us') {
  return {
    region,
    tradeDate: '2026-08-11',
    generatedAt: '2026-08-11T15:05:00+08:00',
    dataUpdatedAt: '2026-08-11T15:04:58+08:00',
    dataStatus: 'ok' as const,
    isStale: false,
    refreshing: false,
    blocks: {
      indices: { status: 'fresh' as const, updatedAt: '2026-08-11T15:04:58+08:00' },
      breadth: { status: region === 'cn' ? 'fresh' as const : 'unsupported' as const },
      sectors: { status: region === 'cn' ? 'fresh' as const : 'unsupported' as const },
      concepts: { status: region === 'cn' ? 'fresh' as const : 'unsupported' as const },
    },
    indices: [{
      code: region === 'cn' ? '000001' : 'SPX',
      name: region === 'cn' ? '上证指数' : 'S&P 500',
      current: 3600,
      change: 18,
      changePct: 0.5,
      high: 3610,
      low: 3575,
    }],
    breadth: {
      available: region === 'cn',
      upCount: region === 'cn' ? 3200 : 0,
      downCount: region === 'cn' ? 1900 : 0,
      flatCount: 0,
      limitUpCount: 70,
      limitDownCount: 5,
      totalAmount: 12345,
    },
    rankings: {
      available: region === 'cn',
      topSectors: region === 'cn' ? [{ name: '电子', changePct: 3.2 }] : [],
      bottomSectors: [],
      topConcepts: [],
      bottomConcepts: [],
    },
    marketLight: {
      status: 'green' as const,
      score: 72,
      label: '偏强',
      temperatureLabel: '偏热',
      reasons: ['市场宽度改善'],
      guidance: '关注结构延续性',
      dataQuality: region === 'cn' ? 'ok' as const : 'partial' as const,
    },
    coverage: { indices: true, breadth: region === 'cn', sectorRankings: region === 'cn' },
    sourceLabel: 'configured_market_data_provider_chain',
  };
}

describe('MarketDashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    getMarketDashboard.mockImplementation(async (region: 'cn' | 'us') => makeDashboard(region));
  });

  it('defaults to A-shares and switches the full dashboard scope with one selector', async () => {
    const onRunReview = vi.fn();
    render(
      <UiLanguageProvider>
        <MarketDashboard onRunReview={onRunReview} />
      </UiLanguageProvider>,
    );

    expect(await screen.findByText('上证指数')).toBeInTheDocument();
    expect(getMarketDashboard).toHaveBeenCalledWith('cn');
    expect(screen.getByText('电子')).toBeInTheDocument();

    fireEvent.change(screen.getByRole('combobox', { name: '市场' }), { target: { value: 'us' } });
    expect(await screen.findByText('S&P 500')).toBeInTheDocument();
    await waitFor(() => expect(getMarketDashboard).toHaveBeenLastCalledWith('us'));
    expect(screen.getAllByText(/国际市场当前以主要指数为主/).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole('button', { name: '生成完整复盘' }));
    expect(onRunReview).toHaveBeenCalledWith('us');
  });

  it('does not let a slow previous market overwrite the current selection', async () => {
    let resolveCn!: (value: ReturnType<typeof makeDashboard>) => void;
    let resolveUs!: (value: ReturnType<typeof makeDashboard>) => void;
    getMarketDashboard.mockImplementation((region: 'cn' | 'us') => new Promise((resolve) => {
      if (region === 'cn') resolveCn = resolve;
      else resolveUs = resolve;
    }));

    render(
      <UiLanguageProvider>
        <MarketDashboard />
      </UiLanguageProvider>,
    );
    await waitFor(() => expect(getMarketDashboard).toHaveBeenCalledWith('cn'));

    fireEvent.change(screen.getByRole('combobox', { name: '市场' }), { target: { value: 'us' } });
    await waitFor(() => expect(getMarketDashboard).toHaveBeenCalledWith('us'));
    resolveUs(makeDashboard('us'));
    expect(await screen.findByText('S&P 500')).toBeInTheDocument();

    resolveCn(makeDashboard('cn'));
    await waitFor(() => expect(screen.queryByText('上证指数')).not.toBeInTheDocument());
    expect(screen.getByText('S&P 500')).toBeInTheDocument();
  });

  it('keeps the last successful dashboard visible when a refresh fails', async () => {
    getMarketDashboard
      .mockResolvedValueOnce(makeDashboard('cn'))
      .mockRejectedValueOnce(new Error('provider timeout'));

    render(
      <UiLanguageProvider>
        <MarketDashboard />
      </UiLanguageProvider>,
    );
    expect(await screen.findByText('上证指数')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '刷新' }));
    expect(await screen.findByText('暂时无法加载市场数据')).toBeInTheDocument();
    expect(screen.getByText('上证指数')).toBeInTheDocument();
  });

  it('does not stack focus refreshes while the same market request is in flight', async () => {
    let resolveCn!: (value: ReturnType<typeof makeDashboard>) => void;
    getMarketDashboard.mockImplementation(() => new Promise((resolve) => {
      resolveCn = resolve;
    }));

    render(
      <UiLanguageProvider>
        <MarketDashboard />
      </UiLanguageProvider>,
    );
    await waitFor(() => expect(getMarketDashboard).toHaveBeenCalledTimes(1));
    fireEvent.focus(window);
    fireEvent.focus(window);
    expect(getMarketDashboard).toHaveBeenCalledTimes(1);

    resolveCn(makeDashboard('cn'));
    expect(await screen.findByText('上证指数')).toBeInTheDocument();
  });

  it('explains partial background refresh without hiding completed blocks', async () => {
    getMarketDashboard.mockResolvedValue({
      ...makeDashboard('cn'),
      dataStatus: 'partial',
      refreshing: true,
      blocks: {
        ...makeDashboard('cn').blocks,
        breadth: { status: 'refreshing', message: 'still fetching' },
      },
    });

    render(
      <UiLanguageProvider>
        <MarketDashboard />
      </UiLanguageProvider>,
    );

    expect(await screen.findByText('上证指数')).toBeInTheDocument();
    expect(screen.getAllByText(/部分覆盖/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/后台刷新中/).length).toBeGreaterThan(0);
  });
});
