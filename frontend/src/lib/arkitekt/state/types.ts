import { ZodType } from "zod";

export interface StateDefinition<T, TKey extends string = string> {
  key: TKey;
  appKey: string;
  schema: ZodType<T>;
}

export interface UseStateOptions<T, U = T> {
  subscribe?: boolean;
  fetchOnMount?: boolean;
  selector?: (state: T) => U;
}

export interface UseStateResult<U> {
  data?: U | null;
  loading: boolean;
  error: Error | null;
  refetch: () => Promise<void>;
  revision: number;
}

export type ResolvedStateDefinition<
  TState extends Record<string, unknown> = Record<string, unknown>,
  TKey extends string = string,
> = StateDefinition<TState, TKey> & { appKey: string };
