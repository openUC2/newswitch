import {
  useLock,
  type LockDefinition,
  type UseLockOptions,
} from '@/lib/arkitekt/locks';

// --- Definition ---
export const CameraParametersDefinition: LockDefinition<'camera_parameters'> = {
  // No description provided
  appKey: 'default',
  key: 'camera_parameters',
};

/**
 * Hook to sync camera_parameters
 */
export const useCameraParametersLock = (options?: UseLockOptions) => {
  return useLock<'camera_parameters'>(CameraParametersDefinition, options);
};
