import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { z } from "zod";
import { selectAppIsLive, useAppStateStore } from "@/lib/arkitekt/app-state";
import {
  getBlockingLock,
  useBlockingLock,
  useLockStoreApi,
} from "@/lib/arkitekt/locks/store";
import { selectTask, useTaskStore } from "@/lib/arkitekt/task/store";
import { useTaskContext } from "@/lib/arkitekt/task/task-context";
import type { AssignOptions, Task } from "@/lib/arkitekt/transport/types";
import type {
  ActionDefinition,
  UseActionOptions,
  UseActionResult,
  UseTransportActionOptions,
  UseTransportActionResult,
} from "./types";

export const useAction = <TArgs, TReturn>(
  definition: ActionDefinition<TArgs, TReturn>,
  options: UseActionOptions = {},
): UseActionResult<TArgs, TReturn> => {
  const {
    autoSubscribe = true,
    onStatusChange,
    onComplete,
    onError,
    onProgress,
  } = options;

  const taskApi = useTaskContext();
  const appKey = definition.appKey;
  const lockStoreApi = useLockStoreApi(appKey);
  const [currentReference, setCurrentReference] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<z.ZodError | null>(
    null,
  );

  const callbacksRef = useRef({
    onStatusChange,
    onComplete,
    onError,
    onProgress,
  });

  useEffect(() => {
    callbacksRef.current = { onStatusChange, onComplete, onError, onProgress };
  }, [onStatusChange, onComplete, onError, onProgress]);

  const taskSelector = useMemo(() => {
    return currentReference
      ? selectTask<TArgs, TReturn>(currentReference)
      : () => undefined;
  }, [currentReference]);

  const task = useTaskStore(appKey, taskSelector) ?? null;
  const isLive = useAppStateStore(appKey, selectAppIsLive);
  const {
    isLocked: hasBlockingLock,
    lockKey: blockingLockKey,
    lockingTaskId,
  } = useBlockingLock(appKey, definition.lockKeys);
  const isLocked = !isLive || hasBlockingLock;
  const lockedBy = lockingTaskId ?? null;

  const currentTaskId = task?.id;
  const status = task?.status ?? null;
  const result = (task?.result as TReturn) ?? null;
  const error = task?.error ?? null;
  const progress = task?.progress ?? null;
  const isLoading = status === "pending" || status === "running";

  const handleTaskUpdate = useCallback((updatedTask: Task) => {
    const cbs = callbacksRef.current;
    if (cbs.onStatusChange) cbs.onStatusChange(updatedTask.status, updatedTask);
    if (cbs.onProgress && updatedTask.progress !== undefined) {
      cbs.onProgress(updatedTask.progress, updatedTask);
    }
    if (updatedTask.status === "completed" && cbs.onComplete) {
      cbs.onComplete(updatedTask.result, updatedTask);
    }
    if (updatedTask.status === "failed" && cbs.onError && updatedTask.error) {
      cbs.onError(updatedTask.error, updatedTask);
    }
  }, []);

  useEffect(() => {
    if (!autoSubscribe || !currentReference) return;

    const unsubscribe = taskApi.subscribeToTask(
      currentReference,
      appKey,
      (updatedTask) => {
        handleTaskUpdate(updatedTask as Task);
      },
    );

    return () => unsubscribe();
  }, [taskApi, appKey, autoSubscribe, currentReference, handleTaskUpdate]);

  const execute = useCallback(
    async (
      args: TArgs,
      opts?: AssignOptions,
    ): Promise<Task<TArgs, TReturn>> => {
      setValidationError(null);

      const { lockKey, lockingTaskId: currentLockingTaskId } = getBlockingLock(
        lockStoreApi.getState().locks,
        definition.lockKeys,
      );

      if (!isLive) {
        throw new Error(
          "Action is unavailable while the app is not in live mode",
        );
      }

      if (lockKey) {
        throw new Error(
          `Action is locked by task ${currentLockingTaskId} (lock: ${lockKey})`,
        );
      }

      const parsed = definition.argsSchema.safeParse(args);
      if (!parsed.success) {
        setValidationError(parsed.error);
        throw parsed.error;
      }

      // Parse first, then encode: defaults (e.g. a model's `__identifier`) are only applied in the
      // decode direction, so encoding `args` straight would drop them. Encoding the parsed value
      // wraps union members back into their `{ __use, __value }` wire envelope; for schemas without
      // a union this is an identity pass.
      const encoded = z.safeEncode(definition.argsSchema, parsed.data);
      if (!encoded.success) {
        setValidationError(encoded.error);
        throw encoded.error;
      }

      const reference = opts?.reference || taskApi.createReference();
      setCurrentReference(reference);

      // `argsSchema` is `ZodType<unknown, TArgs>` (TArgs is the schema's INPUT), so `encoded.data` is
      // statically `unknown`. At runtime it is the wire form of `args` - defaults filled in, branded,
      // unions enveloped - which is structurally still a TArgs, so recording it as the task's args
      // type is sound.
      const wireArgs = encoded.data as TArgs;

      return await taskApi.assign<TArgs, TReturn>(
        appKey,
        definition.name,
        wireArgs,
        { ...opts, reference },
      );
    },
    [taskApi, appKey, definition, isLive, lockStoreApi],
  );

  const assign = useCallback(
    async (args: TArgs, opts?: AssignOptions) => {
      return await execute(args, opts);
    },
    [execute],
  );

  const call = useCallback(
    async (args: TArgs, opts?: AssignOptions): Promise<TReturn> => {
      const reference = opts?.reference || taskApi.createReference();

      await execute(args, { ...opts, reference });

      const taskState = await taskApi.waitForTask<TArgs, TReturn>(
        appKey,
        reference,
      );
      const parsed = definition.returnSchema.safeParse(taskState.result);

      if (!parsed.success) {
        throw new Error(
          `Return value failed schema validation: ${parsed.error.message}`,
        );
      }

      return parsed.data;
    },
    [taskApi, appKey, definition.returnSchema, execute],
  );

  const refresh = useCallback(async (): Promise<void> => {
    if (!currentTaskId) return;
    await taskApi.getTask(appKey, currentTaskId);
  }, [taskApi, appKey, currentTaskId]);

  const cancel = useCallback(async (): Promise<void> => {
    if (!currentTaskId) return;
    await taskApi.cancelTask(appKey, currentTaskId);
  }, [taskApi, appKey, currentTaskId]);

  const clear = useCallback((): void => {
    setCurrentReference(null);
    setValidationError(null);
  }, []);

  return {
    call,
    assign,
    task,
    status,
    result,
    error,
    progress,
    isLive,
    isLoading,
    isLocked,
    lockedBy,
    lockedByKey: blockingLockKey ?? null,
    validationError,
    refresh,
    cancel,
    clear,
  };
};

export const useTransportAction = useAction;

export type { UseTransportActionOptions, UseTransportActionResult };
