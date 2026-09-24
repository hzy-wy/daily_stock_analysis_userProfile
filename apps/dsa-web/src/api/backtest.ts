import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  BacktestRunRequest,
  BacktestRunResponse,
  BacktestTaskAccepted,
  BacktestTaskStatus,
  BacktestResultsResponse,
  BacktestResultItem,
  PerformanceMetrics,
  BacktestPhaseFilter,
} from '../types/backtest';

// ============ API ============

export const backtestApi = {
  /**
   * Trigger backtest evaluation
   */
  run: async (
    params: BacktestRunRequest = {},
    options: { signal?: AbortSignal } = {},
  ): Promise<BacktestRunResponse> => {
    const requestData: Record<string, unknown> = {};
    if (params.code?.trim()) requestData.code = params.code.trim();
    if (params.force) requestData.force = params.force;
    if (params.evalWindowDays != null) requestData.eval_window_days = params.evalWindowDays;
    if (params.minAgeDays != null) requestData.min_age_days = params.minAgeDays;
    if (params.analysisDateFrom) requestData.analysis_date_from = params.analysisDateFrom;
    if (params.analysisDateTo) requestData.analysis_date_to = params.analysisDateTo;
    if (params.limit != null) requestData.limit = params.limit;

    const response = options.signal
      ? await apiClient.post<Record<string, unknown>>(
          '/api/v1/backtest/run/async',
          requestData,
          { signal: options.signal },
        )
      : await apiClient.post<Record<string, unknown>>(
          '/api/v1/backtest/run/async',
          requestData,
        );
    const accepted = toCamelCase<BacktestTaskAccepted>(response.data);
    const deadline = Date.now() + 4 * 60 * 60 * 1000;
    while (Date.now() < deadline) {
      await new Promise<void>((resolve, reject) => {
        if (options.signal?.aborted) {
          reject(new DOMException('回测请求已取消', 'AbortError'));
          return;
        }
        const timer = window.setTimeout(() => {
          options.signal?.removeEventListener('abort', abort);
          resolve();
        }, 750);
        const abort = () => {
          window.clearTimeout(timer);
          reject(new DOMException('回测请求已取消', 'AbortError'));
        };
        options.signal?.addEventListener('abort', abort, { once: true });
      });
      const statusResponse = await apiClient.get<Record<string, unknown>>(
        `/api/v1/backtest/run/tasks/${accepted.taskId}`,
        { signal: options.signal },
      );
      const status = toCamelCase<BacktestTaskStatus>(statusResponse.data);
      if (status.status === 'completed' && status.result) return status.result;
      if (status.status === 'failed' || status.status === 'cancelled') {
        throw new Error(status.error || status.message || '回测任务失败');
      }
    }
    throw new Error('回测任务超时，请稍后刷新结果');
  },

  /**
   * Get paginated backtest results
   */
  getResults: async (params: {
    code?: string;
    evalWindowDays?: number;
    analysisDateFrom?: string;
    analysisDateTo?: string;
    analysisPhase?: BacktestPhaseFilter;
    page?: number;
    limit?: number;
  } = {}): Promise<BacktestResultsResponse> => {
    const { code, evalWindowDays, analysisDateFrom, analysisDateTo, analysisPhase, page = 1, limit = 20 } = params;

    const queryParams: Record<string, string | number> = { page, limit };
    if (code) queryParams.code = code;
    if (evalWindowDays) queryParams.eval_window_days = evalWindowDays;
    if (analysisDateFrom) queryParams.analysis_date_from = analysisDateFrom;
    if (analysisDateTo) queryParams.analysis_date_to = analysisDateTo;
    if (analysisPhase && analysisPhase !== 'all') queryParams.analysis_phase = analysisPhase;

    const response = await apiClient.get<Record<string, unknown>>(
      '/api/v1/backtest/results',
      { params: queryParams },
    );

    const data = toCamelCase<BacktestResultsResponse>(response.data);
    return {
      total: data.total,
      page: data.page,
      limit: data.limit,
      items: (data.items || []).map(item => toCamelCase<BacktestResultItem>(item)),
    };
  },

  /**
   * Get overall performance metrics
   */
  getOverallPerformance: async (params: {
    evalWindowDays?: number;
    analysisDateFrom?: string;
    analysisDateTo?: string;
    analysisPhase?: BacktestPhaseFilter;
  } = {}): Promise<PerformanceMetrics | null> => {
    try {
      const queryParams: Record<string, string | number> = {};
      if (params.evalWindowDays) queryParams.eval_window_days = params.evalWindowDays;
      if (params.analysisDateFrom) queryParams.analysis_date_from = params.analysisDateFrom;
      if (params.analysisDateTo) queryParams.analysis_date_to = params.analysisDateTo;
      if (params.analysisPhase && params.analysisPhase !== 'all') queryParams.analysis_phase = params.analysisPhase;
      const response = await apiClient.get<Record<string, unknown>>(
        '/api/v1/backtest/performance',
        { params: queryParams },
      );
      return toCamelCase<PerformanceMetrics>(response.data);
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'response' in err) {
        const axiosErr = err as { response?: { status?: number } };
        if (axiosErr.response?.status === 404) return null;
      }
      throw err;
    }
  },

  /**
   * Get per-stock performance metrics
   */
  getStockPerformance: async (code: string, params: {
    evalWindowDays?: number;
    analysisDateFrom?: string;
    analysisDateTo?: string;
    analysisPhase?: BacktestPhaseFilter;
  } = {}): Promise<PerformanceMetrics | null> => {
    try {
      const queryParams: Record<string, string | number> = {};
      if (params.evalWindowDays) queryParams.eval_window_days = params.evalWindowDays;
      if (params.analysisDateFrom) queryParams.analysis_date_from = params.analysisDateFrom;
      if (params.analysisDateTo) queryParams.analysis_date_to = params.analysisDateTo;
      if (params.analysisPhase && params.analysisPhase !== 'all') queryParams.analysis_phase = params.analysisPhase;
      const response = await apiClient.get<Record<string, unknown>>(
        `/api/v1/backtest/performance/${encodeURIComponent(code)}`,
        { params: queryParams },
      );
      return toCamelCase<PerformanceMetrics>(response.data);
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'response' in err) {
        const axiosErr = err as { response?: { status?: number } };
        if (axiosErr.response?.status === 404) return null;
      }
      throw err;
    }
  },
};
