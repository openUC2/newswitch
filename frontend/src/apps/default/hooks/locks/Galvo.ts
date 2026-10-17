import {
  useLock,
  type LockDefinition,
  type UseLockOptions,
} from '@/lib/rekuest/locks';

// --- Definition ---
export const GalvoDefinition: LockDefinition<'galvo'> = {
  // No description provided
  appKey: 'default',
  key: 'galvo',
};

/**
 * Hook to sync galvo
 */
export const useGalvoLock = (options?: UseLockOptions) => {
  return useLock<'galvo'>(GalvoDefinition, options);
};
