import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo } from "react";
import type { AppKey, AppsDefinition } from "@/lib/rekuest/types";
import { authFetch } from "@/lib/auth/authFetch";
import { getToken } from "@/lib/auth/token";
import {
  TransportSubscriptionManager,
  type TransportManagerEndpoints,
} from "@/lib/rekuest/transport/subscription-manager";
import { TransportContext } from "./transport-context";
import type {
  AssignInput,
  AssignOptions,
  AssignResponse,
  LockCollectionResponse,
  RetrieverSessionBoundaryResponse,
  SessionBoundaries,
  StateCheckoutResponse,
  StateCollectionResponse,
  StateSegmentsResponse,
  StateView,
  Task,
  TransportConfig,
  TransportContextValue,
  WebSocketSubscriptionInit,
} from "@/lib/rekuest/transport/types";

const DEFAULT_RECONNECT_CONFIG = {
  maxAttempts: 5,
  initialDelay: 1000,
  maxDelay: 30000,
  backoffMultiplier: 2,
} as const;

const DEFAULT_PING_INTERVAL = 30000;

type AppEndpoints = {
  apiEndpoint: string;
  wsUrl: string;
};

export interface TransportProviderProps {
  children: ReactNode;
  config: TransportConfig;
  apps: AppsDefinition;
}

function normalizeTask<TArgs = unknown, TReturn = unknown>(
  data: Record<string, unknown>,
  appKey: AppKey,
): Task<TArgs, TReturn> {
  return {
    id: String(data.task_id ?? data.id),
    appKey,
    action: String(data.action ?? "unknown"),
    args: (data.args ?? {}) as TArgs,
    status: data.status as Task<TArgs, TReturn>["status"],
    result: data.result as TReturn | undefined,
    error: data.error as string | undefined,
    progress: data.progress as number | undefined,
    reference: String(data.reference ?? data.task_id ?? data.id),
    createdAt: new Date(
      String(data.created_at ?? data.createdAt ?? Date.now()),
    ),
    updatedAt: new Date(
      String(data.updated_at ?? data.updatedAt ?? Date.now()),
    ),
  };
}

function createWsBaseUrl(apiEndpoint: string, wsEndpoint?: string) {
  if (wsEndpoint) {
    return wsEndpoint;
  }
  const url = new URL(apiEndpoint);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = url.pathname.replace(/\/$/, "") + "/ws";
  return url.toString();
}

function createSubscriptionInit(
  app: AppsDefinition[AppKey],
): WebSocketSubscriptionInit {
  return {
    type: "INIT",
    action_keys: Object.values(
      app.actions as Record<string, { name?: string }>,
    ).flatMap((definition) => (definition.name ? [definition.name] : [])),
    state_keys: Object.values(
      app.states as Record<string, { key?: string }>,
    ).flatMap((definition) => (definition.key ? [definition.key] : [])),
    lock_keys: Object.values(
      app.locks as Record<string, { key?: string }>,
    ).flatMap((definition) => (definition.key ? [definition.key] : [])),
  };
}

function createSubscriptionInitWithIntervals(
  app: AppsDefinition[AppKey],
  configuredIntervals?: Partial<Record<string, number>>,
): WebSocketSubscriptionInit {
  const baseInit = createSubscriptionInit(app);

  if (!configuredIntervals) {
    return baseInit;
  }

  const mappedIntervals = Object.fromEntries(
    Object.entries(configuredIntervals).flatMap(([configuredKey, interval]) => {
      if (interval == null) {
        return [];
      }

      if (configuredKey === "*") {
        return [[configuredKey, interval] as const];
      }

      const stateDefinition = (app.states as Record<string, { key?: string }>)[
        configuredKey
      ];
      return [[stateDefinition?.key ?? configuredKey, interval] as const];
    }),
  );

  return {
    ...baseInit,
    state_update_intervals: mappedIntervals,
  };
}

function parseSessionBoundaries(data: {
  session_id: string;
  start_global_revision: number;
  end_global_revision: number;
  start_time: string;
  end_time: string;
}): SessionBoundaries {
  return {
    sessionStart: new Date(data.start_time),
    sessionEnd: new Date(data.end_time),
    startRevision: data.start_global_revision,
    endRevision: data.end_global_revision,
    sessionId: data.session_id,
  };
}

export function TransportProvider({
  children,
  config,
  apps,
}: TransportProviderProps) {
  const appKeys = useMemo(() => Object.keys(apps) as AppKey[], [apps]);

  if (appKeys.length === 0) {
    throw new Error("TransportProvider requires at least one configured app.");
  }

  const reconnect = useMemo(
    () => ({ ...DEFAULT_RECONNECT_CONFIG, ...config.reconnect }),
    [config.reconnect],
  );

  const pingInterval = config.pingInterval ?? DEFAULT_PING_INTERVAL;

  const endpointsByApp = useMemo(() => {
    return Object.fromEntries(
      appKeys.map((appKey) => {
        const apiEndpoint =
          config.appEndpoints?.[appKey]?.apiEndpoint ?? config.apiEndpoint;
        const wsUrl = createWsBaseUrl(
          apiEndpoint,
          config.appEndpoints?.[appKey]?.wsEndpoint ?? config.wsEndpoint,
        );

        return [
          appKey,
          {
            apiEndpoint,
            wsUrl,
          } satisfies AppEndpoints,
        ];
      }),
    ) as Record<AppKey, AppEndpoints>;
  }, [appKeys, config.apiEndpoint, config.appEndpoints, config.wsEndpoint]);

  const getApp = useCallback(
    (appKey: AppKey) => {
      const resolvedApp = apps[appKey];

      if (!resolvedApp) {
        throw new Error(`Unknown app key: ${appKey}`);
      }

      return resolvedApp;
    },
    [apps],
  );

  const getEndpoints = useCallback(
    (appKey: AppKey): AppEndpoints => {
      const endpoints = endpointsByApp[appKey];

      if (!endpoints) {
        throw new Error(`No endpoints configured for app key: ${appKey}`);
      }

      return endpoints;
    },
    [endpointsByApp],
  );

  const subscriptionManager = useMemo(
    () =>
      new TransportSubscriptionManager({
        getEndpoints: (appKey) =>
          getEndpoints(appKey) as TransportManagerEndpoints,
        getSubscriptionInit: (appKey) => ({
          ...createSubscriptionInitWithIntervals(
            getApp(appKey),
            config.appStateUpdateIntervals?.[appKey],
          ),
          // The websocket's stand-in for an Authorization header, which browsers
          // will not let us set on a WebSocket. Read here rather than captured
          // above, because this runs on every (re)connect.
          token: getToken(),
        }),
        reconnect,
        pingInterval,
        keepAliveOnNoListeners: true,
      }),
    [
      config.appStateUpdateIntervals,
      getApp,
      getEndpoints,
      pingInterval,
      reconnect,
    ],
  );

  const assignAction = useCallback(
    async <TArgs,>(
      appKey: AppKey,
      actionName: string,
      args: TArgs,
      options?: AssignOptions,
    ): Promise<AssignResponse> => {
      const { apiEndpoint } = getEndpoints(appKey);
      const url = `${apiEndpoint.replace(/\/$/, "")}/${actionName}`;
      const assignInput: AssignInput<TArgs> = {
        args,
        policy: options?.policy,
        agent: options?.agent,
        reference: options?.reference,
        parent: options?.parent,
        cached: options?.cached ?? false,
        log: options?.log ?? true,
        capture: options?.capture ?? false,
        ephemeral: options?.ephemeral ?? false,
        hooks: options?.hooks,
        step: options?.step,
      };

      const response = await authFetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(assignInput),
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(
          `Failed to assign action: ${response.status} ${errorText}`,
        );
      }

      return (await response.json()) as AssignResponse;
    },
    [getEndpoints],
  );

  const fetchTask = useCallback(
    async <TArgs = unknown, TReturn = unknown>(
      appKey: AppKey,
      taskId: string,
    ): Promise<Task<TArgs, TReturn>> => {
      const { apiEndpoint } = getEndpoints(appKey);
      const url = `${apiEndpoint.replace(/\/$/, "")}/tasks/${taskId}`;
      const response = await authFetch(url);

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Failed to get task: ${response.status} ${errorText}`);
      }

      const data = (await response.json()) as Record<string, unknown>;
      return normalizeTask<TArgs, TReturn>(data, appKey);
    },
    [getEndpoints],
  );

  const createTaskMutation = useCallback(
    (endpoint: string) => async (appKey: AppKey, taskId: string) => {
      const { apiEndpoint } = getEndpoints(appKey);
      const url = `${apiEndpoint.replace(/\/$/, "")}/${endpoint}`;
      const response = await authFetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task: taskId }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(
          `Failed to ${endpoint} task: ${response.status} ${errorText}`,
        );
      }
    },
    [getEndpoints],
  );

  const fetchState = useCallback(
    async <T = unknown,>(
      appKey: AppKey,
      stateName: string,
    ): Promise<StateView<T>> => {
      const { apiEndpoint } = getEndpoints(appKey);
      const url = new URL(`${apiEndpoint.replace(/\/$/, "")}/states`);
      url.searchParams.set("state_keys", stateName);

      const response = await authFetch(url.toString());

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(
          `Failed to fetch state: ${response.status} ${errorText}`,
        );
      }

      const data = (await response.json()) as StateCollectionResponse<T>;
      const state = data.states[stateName];

      if (!state) {
        throw new Error(`State ${stateName} not found in collection response.`);
      }

      return { ...state, local_revision: data.current_global_revision ?? 0 };
    },
    [getEndpoints],
  );

  const fetchAll = useCallback(
    async <T = unknown,>(
      appKey: AppKey,
      stateKeys: string[] = [],
    ): Promise<StateCollectionResponse<T>> => {
      const { apiEndpoint } = getEndpoints(appKey);
      const url = new URL(`${apiEndpoint.replace(/\/$/, "")}/states`);

      if (stateKeys.length > 0) {
        url.searchParams.set("state_keys", stateKeys.join(","));
      }

      const response = await authFetch(url.toString());

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(
          `Failed to fetch states: ${response.status} ${errorText}`,
        );
      }

      const data = (await response.json()) as Partial<
        StateCollectionResponse<T>
      >;

      return {
        current_session: data.current_session ?? null,
        current_global_revision: data.current_global_revision ?? null,
        count: data.count ?? Object.keys(data.states ?? {}).length,
        states: data.states ?? {},
        recent_patches: data.recent_patches ?? [],
      };
    },
    [getEndpoints],
  );

  const fetchStateCheckout = useCallback(
    async (
      appKey: AppKey,
      globalRevisionId: string | number,
      stateKeys: string[],
    ): Promise<StateCheckoutResponse> => {
      const { apiEndpoint } = getEndpoints(appKey);
      const url = new URL(`${apiEndpoint.replace(/\/$/, "")}/states/checkout`);
      url.searchParams.set("global_revision_id", String(globalRevisionId));

      for (const stateKey of stateKeys) {
        url.searchParams.append("state_keys", stateKey);
      }

      const response = await authFetch(url.toString());

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(
          `Failed to checkout states: ${response.status} ${errorText}`,
        );
      }

      const data = (await response.json()) as Partial<StateCheckoutResponse>;

      return {
        current_session: data.current_session ?? null,
        current_global_revision: data.current_global_revision ?? null,
        count: data.count ?? Object.keys(data.states ?? {}).length,
        states: data.states ?? {},
        recent_patches: data.recent_patches ?? [],
      };
    },
    [getEndpoints],
  );

  const fetchStateSegments = useCallback(
    async (
      appKey: AppKey,
      fromGlobalRevisionId: string | number,
      toGlobalRevisionId: string | number,
      stateKeys: string[],
    ): Promise<StateSegmentsResponse> => {
      const { apiEndpoint } = getEndpoints(appKey);
      const url = new URL(`${apiEndpoint.replace(/\/$/, "")}/states/segments`);
      url.searchParams.set(
        "from_global_revision_id",
        String(fromGlobalRevisionId),
      );
      url.searchParams.set("to_global_revision_id", String(toGlobalRevisionId));

      for (const stateKey of stateKeys) {
        url.searchParams.append("state_keys", stateKey);
      }

      const response = await authFetch(url.toString());

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(
          `Failed to fetch state segments: ${response.status} ${errorText}`,
        );
      }

      return (await response.json()) as StateSegmentsResponse;
    },
    [getEndpoints],
  );

  const fetchLocks = useCallback(
    async (appKey: AppKey): Promise<Record<string, { task_id: string }>> => {
      const { apiEndpoint } = getEndpoints(appKey);
      const url = `${apiEndpoint.replace(/\/$/, "")}/locks`;
      const response = await authFetch(url);

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(
          `Failed to fetch locks: ${response.status} ${errorText}`,
        );
      }

      const data = (await response.json()) as
        | LockCollectionResponse
        | Record<string, { task_id: string }>
        | Array<{ key: string; task_id: string }>;

      if ("locks" in data && !Array.isArray(data)) {
        return Object.fromEntries(
          Object.entries(data.locks).map(([key, value]) => [
            key,
            { task_id: value.task_id ?? "" },
          ]),
        );
      }

      if (Array.isArray(data)) {
        return Object.fromEntries(
          data.map((entry) => [entry.key, { task_id: entry.task_id }]),
        );
      }

      return data;
    },
    [getEndpoints],
  );

  const fetchActiveSessionBoundaries = useCallback(
    async (appKey: AppKey): Promise<SessionBoundaries> => {
      const { apiEndpoint } = getEndpoints(appKey);
      const url = `${apiEndpoint.replace(/\/$/, "")}/active_session_boundaries`;
      const response = await authFetch(url);

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(
          `Failed to fetch session boundaries: ${response.status} ${errorText}`,
        );
      }

      const data = (await response.json()) as RetrieverSessionBoundaryResponse;

      return parseSessionBoundaries(data);
    },
    [getEndpoints],
  );

  const fetchSessionBoundaries = useCallback(
    async (appKey: AppKey, sessionId: string): Promise<SessionBoundaries> => {
      const { apiEndpoint } = getEndpoints(appKey);
      const url = `${apiEndpoint.replace(/\/$/, "")}/session_boundaries/${sessionId}`;
      const response = await authFetch(url);

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(
          `Failed to fetch session boundaries: ${response.status} ${errorText}`,
        );
      }

      const data = (await response.json()) as RetrieverSessionBoundaryResponse;

      return parseSessionBoundaries(data);
    },
    [getEndpoints],
  );

  useEffect(() => {
    return () => {
      subscriptionManager.dispose(appKeys);
    };
  }, [appKeys, subscriptionManager]);

  const subscribeToMessages = useCallback<
    TransportContextValue["subscribeToMessages"]
  >(
    (options) => subscriptionManager.subscribeToMessages(options),
    [subscriptionManager],
  );

  const subscribeToConnectionState = useCallback<
    TransportContextValue["subscribeToConnectionState"]
  >(
    (appKey, listener) =>
      subscriptionManager.subscribeToConnectionState(appKey, listener),
    [subscriptionManager],
  );

  const reconnectSocket = useCallback<TransportContextValue["reconnectSocket"]>(
    (appKey) => subscriptionManager.reconnectSocket(appKey),
    [subscriptionManager],
  );

  const disconnectSocket = useCallback<
    TransportContextValue["disconnectSocket"]
  >(
    (appKey) => subscriptionManager.disconnectSocket(appKey),
    [subscriptionManager],
  );

  const transportWsUrl = useMemo(
    () => createWsBaseUrl(config.apiEndpoint, config.wsEndpoint),
    [config.apiEndpoint, config.wsEndpoint],
  );

  const contextValue = useMemo<TransportContextValue>(
    () => ({
      apiEndpoint: config.apiEndpoint,
      apps,
      wsUrl: transportWsUrl,
      instanceId: config.instanceId,
      pingInterval,
      reconnect,
      getApp,
      getEndpoints,
      assignAction,
      fetchTask,
      fetchState,
      fetchAll,
      fetchStateCheckout,
      fetchStateSegments,
      fetchLocks,
      fetchSessionBoundaries,
      fetchActiveSessionBoundaries,
      cancelTaskRequest: createTaskMutation("cancel"),
      pauseTaskRequest: createTaskMutation("pause"),
      unpauseTaskRequest: createTaskMutation("resume"),
      stepTaskRequest: createTaskMutation("step"),
      subscribeToMessages,
      subscribeToConnectionState,
      reconnectSocket,
      disconnectSocket,
    }),
    [
      apps,
      assignAction,
      config.apiEndpoint,
      config.instanceId,
      createTaskMutation,
      disconnectSocket,
      fetchActiveSessionBoundaries,
      fetchLocks,
      fetchSessionBoundaries,
      fetchState,
      fetchAll,
      fetchStateCheckout,
      fetchStateSegments,
      fetchTask,
      getApp,
      getEndpoints,
      pingInterval,
      reconnect,
      reconnectSocket,
      subscribeToConnectionState,
      subscribeToMessages,
      transportWsUrl,
    ],
  );

  return (
    <TransportContext.Provider value={contextValue}>
      {children}
    </TransportContext.Provider>
  );
}

export default TransportProvider;
