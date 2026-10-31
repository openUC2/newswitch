import type { LightElement } from "@/apps/default/hooks/states/OpticsState";
import { createStore } from "zustand/vanilla";
import { immer } from "zustand/middleware/immer";
import { createScopedStoreHooks } from "@/lib/arkitekt/createScopedStore";

interface ElementStore {
  selectedElement: LightElement | null;
  setSelectedElement: (element: LightElement | null) => void;
}

export const createElementStore = () =>
  createStore<ElementStore>()(
    immer((set) => ({
      selectedElement: null,
      setSelectedElement: (element) =>
        set((state) => {
          state.selectedElement = element;
        }),
    })),
  );

const { StoreContext: ElementStoreContext, useScopedStore: useElementStore } =
  createScopedStoreHooks<ElementStore>("ElementStore");

export { ElementStoreContext, useElementStore };
