import {
  useTaskStore as useBaseTaskStore,
  type TaskStore,
} from '@/lib/arkitekt/task';

export const useTaskStore = <TSelected>(
  selector: (state: TaskStore) => TSelected,
): TSelected => useBaseTaskStore('default', selector);
