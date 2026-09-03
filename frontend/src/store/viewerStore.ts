import type { Frame } from "@/components/stage/hooks/zarr/types";
import { CachedFetchStore } from "@/components/stage/hooks/zarr/zarr_stores/fetchStore";
import { withToken } from "@/lib/auth/authFetch";
import { TestNoiseZarrStore } from "@/components/stage/hooks/zarr/zarr_stores/noiseStore";
import type { ZarrStore } from "@/components/stage/hooks/zarr/zarr_stores/type";
import { createStore } from "zustand/vanilla";
import { BACKEND_API } from "@/constants";
import { createScopedStoreHooks } from "@/lib/rekuest/createScopedStore";

export type StoreBuilder = (frame: Frame) => ZarrStore;

interface ViewerState {
  // We store the combined projection + view matrix
  zStart: number | null;
  zEnd: number | null;
  tStart: Date | null;
  tEnd: Date | null;
  debug: boolean;
  storeBuilder: StoreBuilder;

  setZRange: (start: number | null, end: number | null) => void;
  setTRange: (start: Date | null, end: Date | null) => void;
  setDebug: (debug: boolean) => void;
}

export const localBuilder = (frame: Frame) => {
  return new TestNoiseZarrStore(frame.id);
};

export const fetchBuilder = (frame: Frame) => {
  // zarrita resolves each chunk against this base and copies the base's query string
  // onto it, so a token here reaches every chunk request. Its own `overrides` option
  // would not work: CachedFetchStore overrides `get` and cannot see them.
  const url = withToken(`${BACKEND_API}/cache/${frame.id}`);
  return new CachedFetchStore(url);
};

export const createViewerStore = () =>
  createStore<ViewerState>((set) => ({
    zStart: 0,
    zEnd: 100,
    tStart: null,
    tEnd: null,
    debug: false,
    storeBuilder: fetchBuilder, // Default to fetchBuilder, can be switched to localBuilder for testing
    setZRange: (start, end) => set({ zStart: start, zEnd: end }),
    setTRange: (start, end) => set({ tStart: start, tEnd: end }),
    setDebug: (debug) => set({ debug }),
  }));

const {
  StoreContext: ViewerStoreContext,
  useScopedStore: useViewerStore,
  useStoreApi: useViewerStoreApi,
} = createScopedStoreHooks<ViewerState>("ViewerStore");

export { ViewerStoreContext, useViewerStore, useViewerStoreApi };
