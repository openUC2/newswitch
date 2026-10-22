import { createStore } from "zustand/vanilla";
import { immer } from "zustand/middleware/immer";
import { createScopedStoreHooks } from "@/lib/arkitekt/createScopedStore";

export interface SelectionState {
  selectedImageId: string | null;
  setSelectedImageId: (id: string | null) => void;
  selectedFrameId: string | null;
  setSelectedFrameId: (id: string | null) => void;
}

export const createSelectionStore = () =>
  createStore<SelectionState>()(
    immer((set) => ({
      selectedImageId: null,
      setSelectedImageId: (id) =>
        set((state) => {
          state.selectedImageId = id;
        }),
      selectedFrameId: null,
      setSelectedFrameId: (id) =>
        set((state) => {
          state.selectedFrameId = id;
        }),
    })),
  );

const {
  StoreContext: SelectionStoreContext,
  useScopedStore: useSelectionStore,
  useStoreApi: useSelectionStoreApi,
} = createScopedStoreHooks<SelectionState>("SelectionStore");

export { SelectionStoreContext, useSelectionStore, useSelectionStoreApi };
