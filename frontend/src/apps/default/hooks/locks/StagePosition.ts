import {
  useLock,
  type LockDefinition,
  type UseLockOptions,
} from '@/lib/arkitekt/locks';

// --- Definition ---
export const StagePositionDefinition: LockDefinition<'stage_position'> = {
  // No description provided
  appKey: 'default',
  key: 'stage_position',
};

/**
 * Hook to sync stage_position
 */
export const useStagePositionLock = (options?: UseLockOptions) => {
  return useLock<'stage_position'>(StagePositionDefinition, options);
};
