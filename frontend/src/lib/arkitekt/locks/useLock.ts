import { useBlockingLock } from "./store";
import type { LockDefinition, UseLockOptions, UseLockResult } from "./types";

export const useLock = <T extends string>(
  definition: LockDefinition<T>,
  options: UseLockOptions = {},
): UseLockResult => {
  void options;
  const appKey = definition.appKey;
  const blockingLock = useBlockingLock(appKey, [definition.key]);

  return {
    isLocked: blockingLock.isLocked,
    lockKey: blockingLock.lockKey,
    lockingTaskId: blockingLock.lockingTaskId,
  };
};
