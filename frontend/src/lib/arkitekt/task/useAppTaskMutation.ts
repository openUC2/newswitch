import { useCallback } from "react";
import { useTaskContext } from "./task-context";
import type { UseAppTaskMutationResult } from "./types";

export const useCancelAppTask = (appKey: string): UseAppTaskMutationResult => {
  const action = useTaskContext();
  type AppKeyInput = Parameters<typeof action.cancelTask>[0];

  return useCallback(
    async (taskId: string): Promise<void> => {
      if (!taskId) return;
      await action.cancelTask(appKey as AppKeyInput, taskId);
    },
    [action, appKey],
  );
};

export const usePauseAppTask = (appKey: string): UseAppTaskMutationResult => {
  const action = useTaskContext();
  type AppKeyInput = Parameters<typeof action.pauseTask>[0];

  return useCallback(
    async (taskId: string): Promise<void> => {
      if (!taskId) return;
      await action.pauseTask(appKey as AppKeyInput, taskId);
    },
    [action, appKey],
  );
};

export const useResumeAppTask = (appKey: string): UseAppTaskMutationResult => {
  const action = useTaskContext();
  type AppKeyInput = Parameters<typeof action.unpauseTask>[0];

  return useCallback(
    async (taskId: string): Promise<void> => {
      if (!taskId) return;
      await action.unpauseTask(appKey as AppKeyInput, taskId);
    },
    [action, appKey],
  );
};

export const useStepAppTask = (appKey: string): UseAppTaskMutationResult => {
  const action = useTaskContext();
  type AppKeyInput = Parameters<typeof action.stepTask>[0];

  return useCallback(
    async (taskId: string): Promise<void> => {
      if (!taskId) return;
      await action.stepTask(appKey as AppKeyInput, taskId);
    },
    [action, appKey],
  );
};
