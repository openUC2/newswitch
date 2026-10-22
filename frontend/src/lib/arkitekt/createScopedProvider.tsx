import type { ComponentProps, ReactNode } from "react";
import { BundleProvider } from "./BundleProvider";
import { ArkitektStoreProvider } from "./ArkitektStoreProvider";
import type { TransportConfig } from "./transport";
import { TransportProvider } from "./transport";
import type { ArkitektAppDefinition, ArkitektAppsDefinition } from "./types";

type ScopedProviderDefinition<
  TKey extends string = string,
  TActions extends Record<string, unknown> = Record<string, unknown>,
  TLocks extends Record<string, unknown> = Record<string, unknown>,
  TStates extends Record<string, unknown> = Record<string, unknown>,
> =
  | ArkitektAppsDefinition<TKey, TActions, TLocks, TStates>
  | ArkitektAppDefinition<TKey, TActions, TLocks, TStates>;

type TransportProviderApps = ComponentProps<typeof TransportProvider>["apps"];

type TransportEndpointConfig = {
  kind?: string;
  url?: string;
  apiEndpoint?: string;
  wsEndpoint?: string;
};

type TransportEndpointMap<TKey extends string> = Partial<
  Record<TKey, TransportEndpointConfig>
>;

type ScopedProviderTransportConfig<TKey extends string> =
  | TransportConfig
  | TransportEndpointMap<TKey>;

type ScopedAppStateUpdateIntervals<TStates extends Record<string, unknown>> =
  Partial<Record<Extract<keyof TStates, string> | "*", number>>;

type ScopedProviderStateUpdateIntervals<
  TKey extends string,
  TStates extends Record<string, unknown>,
> = Partial<Record<TKey, ScopedAppStateUpdateIntervals<TStates>>>;

interface NormalizedDefinition<
  TKey extends string = string,
  TActions extends Record<string, unknown> = Record<string, unknown>,
  TLocks extends Record<string, unknown> = Record<string, unknown>,
  TStates extends Record<string, unknown> = Record<string, unknown>,
> {
  apps: Record<TKey, ArkitektAppDefinition<TKey, TActions, TLocks, TStates>>;
}

export interface CreateScopedProviderOptions<
  TKey extends string = string,
  TActions extends Record<string, unknown> = Record<string, unknown>,
  TLocks extends Record<string, unknown> = Record<string, unknown>,
  TStates extends Record<string, unknown> = Record<string, unknown>,
> {
  definition: ScopedProviderDefinition<TKey, TActions, TLocks, TStates>;
  config: ScopedProviderTransportConfig<TKey>;
  instanceId?: string;
  defaultScope?: string;
  debug?: boolean;
  stateUpdateIntervals?: ScopedProviderStateUpdateIntervals<TKey, TStates>;
  latestPatchesBufferSize?: number;
  reconnect?: TransportConfig["reconnect"];
  pingInterval?: number;
}

export interface ScopedProviderProps<
  TKey extends string = string,
  TStates extends Record<string, unknown> = Record<string, unknown>,
> {
  children: ReactNode;
  scope?: string;
  revision?: string | number;
  instanceId?: string;
  transportConfig?: Partial<TransportConfig>;
  debug?: boolean;
  stateUpdateIntervals?: ScopedProviderStateUpdateIntervals<TKey, TStates>;
  latestPatchesBufferSize?: number;
}

const DEFAULT_SCOPE = "default";
const DEFAULT_INSTANCE_ID = "arkitekt-scoped-provider";

const isSingleAppDefinition = <
  TKey extends string,
  TActions extends Record<string, unknown>,
  TLocks extends Record<string, unknown>,
  TStates extends Record<string, unknown>,
>(
  definition: ScopedProviderDefinition<TKey, TActions, TLocks, TStates>,
): definition is ArkitektAppDefinition<TKey, TActions, TLocks, TStates> => {
  return (
    "key" in definition &&
    "actions" in definition &&
    "locks" in definition &&
    "states" in definition
  );
};

const isTransportConfig = <TKey extends string>(
  config: ScopedProviderTransportConfig<TKey>,
): config is TransportConfig => {
  return "apiEndpoint" in config && "instanceId" in config;
};

const normalizeDefinition = <
  TKey extends string,
  TActions extends Record<string, unknown>,
  TLocks extends Record<string, unknown>,
  TStates extends Record<string, unknown>,
>(
  definition: ScopedProviderDefinition<TKey, TActions, TLocks, TStates>,
): NormalizedDefinition<TKey, TActions, TLocks, TStates> => {
  if (isSingleAppDefinition(definition)) {
    const singleDefinition = definition;
    return {
      apps: {
        [singleDefinition.key]: singleDefinition,
      },
    } as NormalizedDefinition<TKey, TActions, TLocks, TStates>;
  }

  return {
    apps: definition as Record<
      TKey,
      ArkitektAppDefinition<TKey, TActions, TLocks, TStates>
    >,
  };
};

const toApiEndpointFromUrl = (url: string) => {
  const resolved = new URL(url);

  if (resolved.protocol === "ws:" || resolved.protocol === "wss:") {
    resolved.protocol = resolved.protocol === "wss:" ? "https:" : "http:";
  }

  return resolved.toString();
};

const toWsEndpointFromUrl = (url: string) => {
  const resolved = new URL(url);

  if (resolved.protocol === "http:" || resolved.protocol === "https:") {
    resolved.protocol = resolved.protocol === "https:" ? "wss:" : "ws:";
  }

  return resolved.toString();
};

const normalizeEndpoint = (endpoint: TransportEndpointConfig) => {
  const apiEndpoint =
    endpoint.apiEndpoint ??
    (endpoint.url ? toApiEndpointFromUrl(endpoint.url) : undefined);
  const wsEndpoint =
    endpoint.wsEndpoint ??
    (endpoint.url ? toWsEndpointFromUrl(endpoint.url) : undefined);

  if (!apiEndpoint) {
    throw new Error(
      "Scoped provider transport config requires an apiEndpoint or url.",
    );
  }

  return {
    apiEndpoint,
    wsEndpoint,
  };
};

const buildTransportConfig = <TKey extends string>(
  config: ScopedProviderTransportConfig<TKey>,
  instanceId: string,
  reconnect?: TransportConfig["reconnect"],
  pingInterval?: number,
  stateUpdateIntervals?: ScopedProviderStateUpdateIntervals<
    TKey,
    Record<string, unknown>
  >,
  overrides?: Partial<TransportConfig>,
): TransportConfig => {
  if (isTransportConfig(config)) {
    return {
      ...config,
      ...overrides,
      instanceId: overrides?.instanceId ?? instanceId ?? config.instanceId,
      appStateUpdateIntervals:
        overrides?.appStateUpdateIntervals ??
        stateUpdateIntervals ??
        config.appStateUpdateIntervals,
      reconnect: overrides?.reconnect ?? reconnect ?? config.reconnect,
      pingInterval:
        overrides?.pingInterval ?? pingInterval ?? config.pingInterval,
    };
  }

  const selectedEntry = Object.entries(config).find(
    (entry): entry is [string, TransportEndpointConfig] =>
      entry[1] !== undefined,
  );

  const selected = selectedEntry?.[1];

  if (!selected) {
    throw new Error("No transport endpoint configured for scoped provider.");
  }

  const normalizedSelected = normalizeEndpoint(selected);
  const appEndpoints = Object.fromEntries(
    Object.entries(config)
      .filter(
        (entry): entry is [string, TransportEndpointConfig] =>
          entry[1] !== undefined,
      )
      .map(([key, value]) => [key, normalizeEndpoint(value)]),
  );

  return {
    apiEndpoint: normalizedSelected.apiEndpoint,
    wsEndpoint: normalizedSelected.wsEndpoint,
    instanceId: overrides?.instanceId ?? instanceId,
    appStateUpdateIntervals:
      overrides?.appStateUpdateIntervals ?? stateUpdateIntervals,
    reconnect: overrides?.reconnect ?? reconnect,
    pingInterval: overrides?.pingInterval ?? pingInterval,
    appEndpoints,
    ...overrides,
  };
};

const buildScopeKey = (scope: string, revision?: string | number) => {
  return [scope, revision == null ? null : `revision-${revision}`]
    .filter((value): value is string => value !== null)
    .join(":");
};

export function createScopedProvider<
  TKey extends string = string,
  TActions extends Record<string, unknown> = Record<string, unknown>,
  TLocks extends Record<string, unknown> = Record<string, unknown>,
  TStates extends Record<string, unknown> = Record<string, unknown>,
>({
  definition,
  config,
  instanceId = DEFAULT_INSTANCE_ID,
  defaultScope = DEFAULT_SCOPE,
  reconnect,
  debug: debugOverride,
  stateUpdateIntervals: stateUpdateIntervalsOverride,
  latestPatchesBufferSize: latestPatchesBufferSizeOverride,
  pingInterval,
}: CreateScopedProviderOptions<TKey, TActions, TLocks, TStates>) {
  const normalizedDefinition = normalizeDefinition(definition);

  function ScopedProvider({
    children,
    scope = defaultScope,
    revision,
    transportConfig,
    instanceId: instanceIdOverride,
    debug = debugOverride,
    stateUpdateIntervals = stateUpdateIntervalsOverride,
    latestPatchesBufferSize = latestPatchesBufferSizeOverride,
  }: ScopedProviderProps<TKey, TStates>) {
    const scopeKey = buildScopeKey(scope, revision);
    const resolvedConfig = buildTransportConfig(
      config,
      instanceIdOverride ?? instanceId,
      reconnect,
      pingInterval,
      stateUpdateIntervals as ScopedProviderStateUpdateIntervals<
        TKey,
        Record<string, unknown>
      >,
      transportConfig,
    );

    return (
      <TransportProvider
        key={scopeKey}
        apps={normalizedDefinition.apps as TransportProviderApps}
        config={resolvedConfig}
      >
        <ArkitektStoreProvider
          scope={scopeKey}
          debug={debug}
          latestPatchesBufferSize={latestPatchesBufferSize}
        >
          <BundleProvider>{children}</BundleProvider>
        </ArkitektStoreProvider>
      </TransportProvider>
    );
  }

  ScopedProvider.displayName = "ScopedArkitektProvider";

  return ScopedProvider;
}
