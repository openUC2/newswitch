import {
  useLock,
  type LockDefinition,
  type UseLockOptions,
} from '@/lib/arkitekt/locks';

// --- Definition ---
export const FilterBankDefinition: LockDefinition<'filter_bank'> = {
  // No description provided
  appKey: 'default',
  key: 'filter_bank',
};

/**
 * Hook to sync filter_bank
 */
export const useFilterBankLock = (options?: UseLockOptions) => {
  return useLock<'filter_bank'>(FilterBankDefinition, options);
};
