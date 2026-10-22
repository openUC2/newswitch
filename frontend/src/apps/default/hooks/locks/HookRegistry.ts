import {
  useLock,
  type LockDefinition,
  type UseLockOptions,
} from '@/lib/arkitekt/locks';

// --- Definition ---
export const HookRegistryDefinition: LockDefinition<'hook_registry'> = {
  // No description provided
  appKey: 'default',
  key: 'hook_registry',
};

/**
 * Hook to sync hook_registry
 */
export const useHookRegistryLock = (options?: UseLockOptions) => {
  return useLock<'hook_registry'>(HookRegistryDefinition, options);
};
