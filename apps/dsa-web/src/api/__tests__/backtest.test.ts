import { afterEach, describe, expect, it, vi } from 'vitest';
import { backtestApi } from '../backtest';
import apiClient from '../index';

vi.mock('../index', () => ({ default: { get: vi.fn(), post: vi.fn() } }));

describe('backtestApi.run', () => {
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.clearAllMocks(); });

  it('submits a background job and polls until completion', async () => {
    vi.useFakeTimers();
    vi.mocked(apiClient.post).mockResolvedValue({ data: {
      task_id: 'job-1', status: 'pending', message: 'submitted',
    } } as never);
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ data: { task_id: 'job-1', status: 'processing', progress: 10 } } as never)
      .mockResolvedValueOnce({ data: { task_id: 'job-1', status: 'completed', progress: 100,
        result: { processed: 1, saved: 1, completed: 1, insufficient: 0, errors: 0 } } } as never);
    const pending = backtestApi.run({ code: '600519' });
    await vi.advanceTimersByTimeAsync(1500);
    await expect(pending).resolves.toMatchObject({ saved: 1 });
    expect(apiClient.post).toHaveBeenCalledWith('/api/v1/backtest/run/async', { code: '600519' });
    expect(apiClient.get).toHaveBeenCalledTimes(2);
  });

  it('surfaces a failed background job', async () => {
    vi.useFakeTimers();
    vi.mocked(apiClient.post).mockResolvedValue({ data: {
      task_id: 'job-2', status: 'pending', message: 'submitted',
    } } as never);
    vi.mocked(apiClient.get).mockResolvedValue({ data: {
      task_id: 'job-2', status: 'failed', progress: 10, error: 'upstream failed',
    } } as never);
    const pending = backtestApi.run();
    const assertion = expect(pending).rejects.toThrow('upstream failed');
    await vi.advanceTimersByTimeAsync(750);
    await assertion;
  });

  it('stops polling after the client deadline', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: {
      task_id: 'job-3', status: 'pending', message: 'submitted',
    } } as never);
    vi.spyOn(Date, 'now')
      .mockReturnValueOnce(0)
      .mockReturnValue(4 * 60 * 60 * 1000);

    await expect(backtestApi.run()).rejects.toThrow('回测任务超时');
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it('stops polling when the caller aborts', async () => {
    vi.useFakeTimers();
    vi.mocked(apiClient.post).mockResolvedValue({ data: {
      task_id: 'job-4', status: 'pending', message: 'submitted',
    } } as never);
    const controller = new AbortController();
    const pending = backtestApi.run({}, { signal: controller.signal });
    await Promise.resolve();
    controller.abort();

    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(apiClient.get).not.toHaveBeenCalled();
  });
});
