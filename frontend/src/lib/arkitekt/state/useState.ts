import { useCallback, useEffect } from "react";
import {
  selectError,
  selectLoading,
  selectRevision,
  selectState,
  useGlobalStateStore,
} from "./store";
import { useStateContext } from "@/lib/arkitekt/state/state-context";
import type { StateDefinition, UseStateOptions, UseStateResult } from "./types";

export const buildUseState = <T extends Record<string, unknown>>(
  definition: StateDefinition<T>,
) => {
  return <U = T>(options: UseStateOptions<T, U> = {}): UseStateResult<U> => {
    return useState<T, U>(definition, options);
  };
};

export const useState = <
  T extends Record<string, unknown>,
  U = T,
  TKey extends string = string,
>(
  definition: StateDefinition<T, TKey>,
  options: UseStateOptions<T, U> = {},
): UseStateResult<U> => {
  const { subscribe = false, fetchOnMount = false, selector } = options;
  const stateContext = useStateContext();
  void subscribe;

  const appKey = definition.appKey;

  const rawData =
    useGlobalStateStore(appKey, selectState<T>(definition.key)) ?? null;
  const revision = useGlobalStateStore(appKey, selectRevision(definition.key));

  const data =
    rawData && selector ? selector(rawData) : (rawData as unknown as U | null);

  const loading = useGlobalStateStore(appKey, selectLoading(definition.key));
  const error = useGlobalStateStore(appKey, selectError(definition.key));

  const refetch = useCallback(async () => {
    await stateContext.refetchState(definition);
  }, [definition, stateContext]);

  useEffect(() => {
    if (fetchOnMount) {
      void stateContext.ensureState(definition);
    }
  }, [definition, fetchOnMount, stateContext]);

  return {
    data,
    loading,
    error,
    refetch,
    revision,
  };
};
