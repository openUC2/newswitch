import {
  useLockStore as useBaseLockStore,
  type LockStore,
} from '@/lib/arkitekt/locks';

export const useLockStore = <TSelected>(
  selector: (state: LockStore) => TSelected,
): TSelected => useBaseLockStore('default', selector);
