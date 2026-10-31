import {
  useLock,
  type LockDefinition,
  type UseLockOptions,
} from '@/lib/arkitekt/locks';

// --- Definition ---
export const DetectorDefinition: LockDefinition<'detector'> = {
  // No description provided
  appKey: 'default',
  key: 'detector',
};

/**
 * Hook to sync detector
 */
export const useDetectorLock = (options?: UseLockOptions) => {
  return useLock<'detector'>(DetectorDefinition, options);
};
