import {
  useLock,
  type LockDefinition,
  type UseLockOptions,
} from '@/lib/arkitekt/locks';

// --- Definition ---
export const MotionDefinition: LockDefinition<'motion'> = {
  // No description provided
  appKey: 'default',
  key: 'motion',
};

/**
 * Hook to sync motion
 */
export const useMotionLock = (options?: UseLockOptions) => {
  return useLock<'motion'>(MotionDefinition, options);
};
