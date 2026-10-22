export interface LockDefinition<T extends string> {
  key: T;
  appKey: string;
}

export interface UseLockOptions {
  subscribe?: boolean;
  fetchOnMount?: boolean;
}

export interface UseLockResult {
  isLocked: boolean;
  lockKey: string | null;
  lockingTaskId: string | undefined;
}
