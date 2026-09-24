import { useEffect, useRef } from 'react';
import type { TaskInfo } from '../types/analysis';
import { useTaskStream } from './useTaskStream';

type UseDashboardLifecycleOptions = {
  loadInitialHistory: () => Promise<void>;
  refreshHistory: (silent?: boolean) => Promise<void>;
  refreshHistoryForCompletedTask?: (task: TaskInfo) => Promise<void>;
  refreshActiveTasks: () => Promise<void>;
  loadStockBar: () => Promise<void>;
  refreshStockBar: () => Promise<void>;
  loadMarketReviewHistory?: () => Promise<void>;
  refreshMarketReviewHistory?: (silent?: boolean) => Promise<void>;
  syncTaskCreated: (task: TaskInfo) => void;
  syncTaskUpdated: (task: TaskInfo) => void;
  syncTaskFailed: (task: TaskInfo) => void;
  removeTask: (taskId: string) => void;
  onDashboardDataRefresh?: () => void;
  onCompletedTaskDataRefreshed?: (task: TaskInfo) => void;
  enabled?: boolean;
};

export function useDashboardLifecycle({
  loadInitialHistory,
  refreshHistory,
  refreshHistoryForCompletedTask,
  refreshActiveTasks,
  loadStockBar,
  refreshStockBar,
  loadMarketReviewHistory,
  refreshMarketReviewHistory,
  syncTaskCreated,
  syncTaskUpdated,
  syncTaskFailed,
  removeTask,
  onDashboardDataRefresh,
  onCompletedTaskDataRefreshed,
  enabled = true,
}: UseDashboardLifecycleOptions): void {
  const removalTimeoutsRef = useRef<number[]>([]);
  const backgroundRefreshRef = useRef(false);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    void loadInitialHistory();
    void loadStockBar();
    void loadMarketReviewHistory?.();
    void refreshActiveTasks();
  }, [enabled, loadInitialHistory, loadMarketReviewHistory, loadStockBar, refreshActiveTasks]);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    const refresh = async () => {
      if (document.visibilityState === 'hidden' || backgroundRefreshRef.current) {
        return;
      }
      backgroundRefreshRef.current = true;
      try {
        await Promise.allSettled([
          Promise.resolve().then(() => refreshHistory(true)),
          Promise.resolve().then(() => refreshStockBar()),
          Promise.resolve().then(() => refreshMarketReviewHistory?.(true)),
          Promise.resolve().then(() => refreshActiveTasks()),
        ]);
      } finally {
        backgroundRefreshRef.current = false;
      }
    };
    const triggerRefresh = () => {
      if (document.visibilityState !== 'hidden' && !backgroundRefreshRef.current) {
        void refresh();
        onDashboardDataRefresh?.();
      }
    };
    const intervalId = window.setInterval(triggerRefresh, 30_000);

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        triggerRefresh();
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      window.clearInterval(intervalId);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [enabled, onDashboardDataRefresh, refreshHistory, refreshMarketReviewHistory, refreshStockBar, refreshActiveTasks]);

  useEffect(() => {
    return () => {
      removalTimeoutsRef.current.forEach((timeoutId) => window.clearTimeout(timeoutId));
      removalTimeoutsRef.current = [];
    };
  }, []);

  const scheduleTaskRemoval = (taskId: string, delayMs: number) => {
    const timeoutId = window.setTimeout(() => {
      removeTask(taskId);
      removalTimeoutsRef.current = removalTimeoutsRef.current.filter((item) => item !== timeoutId);
    }, delayMs);

    removalTimeoutsRef.current.push(timeoutId);
  };

  useTaskStream({
    onResyncRequired: () => {
      void Promise.allSettled([
        refreshActiveTasks(), refreshHistory(true), refreshStockBar(),
        refreshMarketReviewHistory?.(true),
      ]);
      onDashboardDataRefresh?.();
    },
    onTaskCreated: syncTaskCreated,
    onTaskStarted: syncTaskUpdated,
    onTaskProgress: syncTaskUpdated,
    onConnected: () => {
      void refreshActiveTasks();
    },
    onTaskCompleted: (task) => {
      syncTaskUpdated(task);
      const historyRefresh = refreshHistoryForCompletedTask
        ? refreshHistoryForCompletedTask(task)
        : refreshHistory(true);
      const stockBarRefresh = refreshStockBar();
      void Promise.allSettled([historyRefresh, stockBarRefresh]).then(() => {
        onCompletedTaskDataRefreshed?.(task);
      });
      void refreshMarketReviewHistory?.(true);
      scheduleTaskRemoval(task.taskId, 2_000);
    },
    onTaskFailed: (task) => {
      syncTaskFailed(task);
      scheduleTaskRemoval(task.taskId, 5_000);
    },
    onError: () => {
      console.warn('SSE connection disconnected, reconnecting...');
    },
    enabled,
  });
}

export default useDashboardLifecycle;
