import {
  useGlobalStateStore as useBaseStateStore,
  type GlobalStateStore,
} from '@/lib/arkitekt/state';

export const useStateStore = <TSelected>(
  selector: (state: GlobalStateStore) => TSelected,
): TSelected => useBaseStateStore('default', selector);
