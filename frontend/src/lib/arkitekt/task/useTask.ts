import { useCallback, useMemo } from "react";
import type { AppKey } from "@/lib/arkitekt/types";
import { selectTask, useTaskStore } from "@/lib/arkitekt/task/store";
import type { Task } from "@/lib/arkitekt/transport/types";
import { useTaskContext } from "./task-context";

export interface UseTaskOptions {
  appKey: AppKey;
}

export interface UseTaskResult<TArgs = unknown, TReturn = unknown> {
  task: Task<TArgs, TReturn> | null;
  refresh: () => Promise<void>;
  cancel: () => Promise<void>;
  pause: () => Promise<void>;
  unpause: () => Promise<void>;
  step: () => Promise<void>;
}

export function useTask<TArgs = unknown, TReturn = unknown>(
  taskId: string | null | undefined,
  options: UseTaskOptions,
): UseTaskResult<TArgs, TReturn> {
  const action = useTaskContext();
  const { appKey } = options;
  const selector = useMemo(
    () => (taskId ? selectTask<TArgs, TReturn>(taskId) : () => undefined),
    [taskId],
  );
  const task = useTaskStore(appKey, selector) ?? null;

  const refresh = useCallback(async () => {
    if (!taskId) return;
    await action.getTask(appKey, taskId);
  }, [action, appKey, taskId]);

  const cancel = useCallback(async () => {
    if (!taskId) return;
    await action.cancelTask(appKey, taskId);
  }, [action, appKey, taskId]);

  const pause = useCallback(async () => {
    if (!taskId) return;
    await action.pauseTask(appKey, taskId);
  }, [action, appKey, taskId]);

  const unpause = useCallback(async () => {
    if (!taskId) return;
    await action.unpauseTask(appKey, taskId);
  }, [action, appKey, taskId]);

  const step = useCallback(async () => {
    if (!taskId) return;
    await action.stepTask(appKey, taskId);
  }, [action, appKey, taskId]);

  return { task, refresh, cancel, pause, unpause, step };
}
