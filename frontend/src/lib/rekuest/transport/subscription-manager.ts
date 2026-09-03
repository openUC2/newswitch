import { WS_UNAUTHORIZED_CLOSE_CODE } from "@/lib/auth/authFetch";
import { clearToken } from "@/lib/auth/token";
import type { AppKey } from "@/lib/rekuest/types";
import type {
  FromAgentMessage,
  TransportConfig,
  TransportMessageSubscription,
  TransportSocketConnectionState,
  WebSocketSubscriptionInit,
} from "@/lib/rekuest/transport/types";

export type TransportManagerEndpoints = {
  wsUrl: string;
};

type SocketState = TransportSocketConnectionState;
type ReconnectConfig = Required<NonNullable<TransportConfig["reconnect"]>>;

type AppChannelState = {
  ws: WebSocket | null;
  listeners: Set<(message: FromAgentMessage) => void>;
  connectionState: SocketState;
  reconnectTimeoutId: ReturnType<typeof setTimeout> | null;
  shouldReconnect: boolean;
};

export interface TransportSubscriptionManagerOptions {
  getEndpoints: (appKey: AppKey) => TransportManagerEndpoints;
  getSubscriptionInit: (appKey: AppKey) => WebSocketSubscriptionInit;
  reconnect: ReconnectConfig;
  pingInterval: number;
  keepAliveOnNoListeners?: boolean;
}

function createInitialConnectionState(): SocketState {
  return {
    isConnected: false,
    isReconnecting: false,
    isUnconnectable: false,
    reconnectAttempt: 0,
  };
}

/**
 * Owns websocket channel lifecycle independently from React components.
 *
 * The manager keeps channel sockets stable across transient subscribe/unsubscribe
 * churn. This avoids task websocket disconnects when providers briefly remount
 * or swap listeners during React updates.
 */
export class TransportSubscriptionManager {
  private readonly channelStates = new Map<AppKey, AppChannelState>();

  private readonly connectionListeners = new Map<
    AppKey,
    Set<(state: SocketState) => void>
  >();

  private readonly pingIntervals = new Map<
    string,
    ReturnType<typeof setInterval>
  >();

  private readonly getEndpoints: TransportSubscriptionManagerOptions["getEndpoints"];

  private readonly getSubscriptionInit: TransportSubscriptionManagerOptions["getSubscriptionInit"];

  private readonly reconnect: ReconnectConfig;

  private readonly pingInterval: number;

  private readonly keepAliveOnNoListeners: boolean;

  constructor({
    getEndpoints,
    getSubscriptionInit,
    reconnect,
    pingInterval,
    keepAliveOnNoListeners = true,
  }: TransportSubscriptionManagerOptions) {
    this.getEndpoints = getEndpoints;
    this.getSubscriptionInit = getSubscriptionInit;
    this.reconnect = reconnect;
    this.pingInterval = pingInterval;
    this.keepAliveOnNoListeners = keepAliveOnNoListeners;
  }

  subscribeToMessages = (options: {
    appKey: AppKey;
    listener: (message: FromAgentMessage) => void;
  }): TransportMessageSubscription => {
    const state = this.ensureChannelState(options.appKey);

    state.listeners.add(options.listener);
    state.shouldReconnect = true;
    this.connectChannel(options.appKey);

    return {
      unsubscribe: () => {
        state.listeners.delete(options.listener);

        if (state.listeners.size > 0 || this.keepAliveOnNoListeners) {
          return;
        }

        state.shouldReconnect = false;
        if (state.reconnectTimeoutId) {
          clearTimeout(state.reconnectTimeoutId);
          state.reconnectTimeoutId = null;
        }
        this.cleanupSocket(options.appKey);
        state.connectionState = createInitialConnectionState();
        this.notifyConnectionListeners(options.appKey);
      },
    };
  };

  subscribeToConnectionState = (
    appKey: AppKey,
    listener: (state: SocketState) => void,
  ) => {
    const listeners = this.connectionListeners.get(appKey) ?? new Set();
    listeners.add(listener);
    this.connectionListeners.set(appKey, listeners);
    this.notifyConnectionListeners(appKey);

    return () => {
      const currentListeners = this.connectionListeners.get(appKey);
      if (!currentListeners) {
        return;
      }

      currentListeners.delete(listener);
      if (currentListeners.size === 0) {
        this.connectionListeners.delete(appKey);
      }
    };
  };

  reconnectSocket = (appKey: AppKey) => {
    const state = this.channelStates.get(appKey);

    if (!state) {
      return;
    }

    state.shouldReconnect = true;
    state.connectionState = createInitialConnectionState();
    if (state.reconnectTimeoutId) {
      clearTimeout(state.reconnectTimeoutId);
      state.reconnectTimeoutId = null;
    }
    this.cleanupSocket(appKey);
    this.connectChannel(appKey);
    this.notifyConnectionListeners(appKey);
  };

  disconnectSocket = (appKey: AppKey) => {
    const state = this.channelStates.get(appKey);

    if (!state) {
      return;
    }

    state.shouldReconnect = false;
    if (state.reconnectTimeoutId) {
      clearTimeout(state.reconnectTimeoutId);
      state.reconnectTimeoutId = null;
    }
    this.cleanupSocket(appKey);
    state.connectionState = createInitialConnectionState();
    this.notifyConnectionListeners(appKey);
  };

  dispose = (appKeys: AppKey[]) => {
    appKeys.forEach((appKey) => this.disconnectSocket(appKey));
    this.channelStates.clear();
    this.connectionListeners.clear();
    this.pingIntervals.forEach((intervalId) => clearInterval(intervalId));
    this.pingIntervals.clear();
  };

  private ensureChannelState(appKey: AppKey): AppChannelState {
    const existingState = this.channelStates.get(appKey);
    if (existingState) {
      return existingState;
    }

    const nextState: AppChannelState = {
      ws: null,
      listeners: new Set(),
      connectionState: createInitialConnectionState(),
      reconnectTimeoutId: null,
      shouldReconnect: true,
    };

    this.channelStates.set(appKey, nextState);
    return nextState;
  }

  private notifyConnectionListeners(appKey: AppKey) {
    const listeners = this.connectionListeners.get(appKey);

    if (!listeners || listeners.size === 0) {
      return;
    }

    const aggregateState =
      this.channelStates.get(appKey)?.connectionState ??
      createInitialConnectionState();

    listeners.forEach((listener) => listener(aggregateState));
  }

  private stopPing(appKey: AppKey) {
    const intervalId = this.pingIntervals.get(appKey);

    if (!intervalId) {
      return;
    }

    clearInterval(intervalId);
    this.pingIntervals.delete(appKey);
  }

  private cleanupSocket(appKey: AppKey) {
    this.stopPing(appKey);
    const state = this.channelStates.get(appKey);

    if (!state?.ws) {
      return;
    }

    state.ws.onopen = null;
    state.ws.onmessage = null;
    state.ws.onclose = null;
    state.ws.onerror = null;

    if (
      state.ws.readyState === WebSocket.OPEN ||
      state.ws.readyState === WebSocket.CONNECTING
    ) {
      state.ws.close(1000, "Client cleanup");
    }

    state.ws = null;
  }

  private scheduleReconnect(appKey: AppKey) {
    const state = this.channelStates.get(appKey);

    if (!state) {
      return;
    }

    const nextAttempt = state.connectionState.reconnectAttempt + 1;
    state.connectionState = {
      ...state.connectionState,
      isConnected: false,
      isReconnecting: nextAttempt <= this.reconnect.maxAttempts,
      reconnectAttempt: nextAttempt,
      isUnconnectable: nextAttempt > this.reconnect.maxAttempts,
    };
    this.notifyConnectionListeners(appKey);

    if (nextAttempt > this.reconnect.maxAttempts) {
      return;
    }

    const delay = Math.min(
      this.reconnect.initialDelay *
        Math.pow(this.reconnect.backoffMultiplier, nextAttempt - 1),
      this.reconnect.maxDelay,
    );

    state.reconnectTimeoutId = setTimeout(() => {
      state.reconnectTimeoutId = null;
      if (state.shouldReconnect) {
        this.connectChannel(appKey);
      }
    }, delay);
  }

  private connectChannel(appKey: AppKey) {
    const state = this.ensureChannelState(appKey);

    if (state.connectionState.isUnconnectable) {
      this.notifyConnectionListeners(appKey);
      return;
    }

    if (
      state.ws?.readyState === WebSocket.OPEN ||
      state.ws?.readyState === WebSocket.CONNECTING
    ) {
      return;
    }

    const url = this.getEndpoints(appKey).wsUrl;

    this.cleanupSocket(appKey);

    const ws = new WebSocket(url);
    state.ws = ws;

    ws.onopen = () => {
      state.connectionState = {
        isConnected: true,
        isReconnecting: false,
        isUnconnectable: false,
        reconnectAttempt: 0,
      };

      ws.send(JSON.stringify(this.getSubscriptionInit(appKey)));
      this.notifyConnectionListeners(appKey);
      this.stopPing(appKey);
      this.pingIntervals.set(
        appKey,
        setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "ping" }));
          }
        }, this.pingInterval),
      );
    };

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data) as FromAgentMessage;
      console.log(
        `[TransportSubscriptionManager] Received message for ${appKey}:`,
        message,
      );
      state.listeners.forEach((listener) => {
        // One listener throwing must not starve the others of this message.
        try {
          listener(message);
        } catch (error) {
          console.error(
            `[TransportSubscriptionManager] Listener failed for ${appKey}:`,
            error,
          );
        }
      });
    };

    ws.onerror = () => {
      state.connectionState = {
        ...state.connectionState,
        isConnected: false,
      };
      this.notifyConnectionListeners(appKey);
    };

    ws.onclose = (event) => {
      this.stopPing(appKey);
      state.connectionState = {
        ...state.connectionState,
        isConnected: false,
      };
      this.notifyConnectionListeners(appKey);

      // A rejected token is not a transient failure. Without this branch it would
      // fall into the backoff below and retry for ~30s before giving up, leaving the
      // user on a silently dead screen instead of back at the login page.
      if (event.code === WS_UNAUTHORIZED_CLOSE_CODE) {
        console.warn(
          `[TransportSubscriptionManager] ${appKey} rejected: not authorized`,
        );
        state.shouldReconnect = false;
        clearToken();
        return;
      }

      if (state.shouldReconnect) {
        this.scheduleReconnect(appKey);
      }
    };
  }
}
