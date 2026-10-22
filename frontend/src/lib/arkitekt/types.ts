export interface ArkitektAppDefinition<
  TKey extends string = string,
  TActions extends Record<string, unknown> = Record<string, unknown>,
  TLocks extends Record<string, unknown> = Record<string, unknown>,
  TStates extends Record<string, unknown> = Record<string, unknown>,
> {
  key: TKey;
  actions: TActions;
  locks: TLocks;
  states: TStates;
}

export type ArkitektAppsDefinition<
  TKey extends string = string,
  TActions extends Record<string, unknown> = Record<string, unknown>,
  TLocks extends Record<string, unknown> = Record<string, unknown>,
  TStates extends Record<string, unknown> = Record<string, unknown>,
> = Record<TKey, ArkitektAppDefinition<TKey, TActions, TLocks, TStates>>;

export type AppKey = string;

export type AppDefinition<
  TKey extends string = string,
  TActions extends Record<string, unknown> = Record<string, unknown>,
  TLocks extends Record<string, unknown> = Record<string, unknown>,
  TStates extends Record<string, unknown> = Record<string, unknown>,
> = ArkitektAppDefinition<TKey, TActions, TLocks, TStates>;

export type AppsDefinition<
  TKey extends string = string,
  TActions extends Record<string, unknown> = Record<string, unknown>,
  TLocks extends Record<string, unknown> = Record<string, unknown>,
  TStates extends Record<string, unknown> = Record<string, unknown>,
> = ArkitektAppsDefinition<TKey, TActions, TLocks, TStates>;
