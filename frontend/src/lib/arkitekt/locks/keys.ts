export const getScopedLockKey = (appKey: string, lockKey: string) =>
  `${appKey}::lock::${lockKey}`;

export const scopeLockKeys = (appKey: string, lockKeys: string[]) =>
  lockKeys.map((lockKey) => getScopedLockKey(appKey, lockKey));
