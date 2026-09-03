import type {
  AppDefinition,
  AppKey,
  AppsDefinition,
} from "@/lib/rekuest/types";

export type TaskStatus =
  | "pending"
  | "running"
  | "completed"
  | "submitted"
  | "failed"
  | "cancelled"
  | "paused"
  | "interrupted";

export interface Task<TArgs = unknown, TReturn = unknown> {
  id: string;
  appKey?: AppKey;
  action: string;
  args: TArgs;
  reference: string;
  status: TaskStatus;
  result?: TReturn;
  error?: string;
  progress?: number;
  progressMessage?: string;
  notify?: boolean;
  createdAt: Date;
  updatedAt: Date;
}

export interface TaskView {
  task: string;
  action_key: string;
  interface: string | null;
  extension: string | null;
  user: string | null;
  app: string | null;
  action: string | null;
  running: boolean;
  actor_id: string | null;
}

export interface TaskCollectionResponse {
  count: number;
  tasks: Record<string, TaskView>;
}

export interface RetrieverSessionInfoResponse {
  current_session: string | null;
}

export interface RetrieverTaskBoundaryResponse {
  correlation_id: string;
  start_global_revision: number;
  end_global_revision: number;
  start_time: string;
  end_time: string;
}

export interface RetrieverSessionBoundaryResponse {
  session_id: string;
  start_global_revision: number;
  end_global_revision: number;
  start_time: string;
  end_time: string;
}

export interface RetrieverSnapshotResponse<T = unknown> {
  timepoint: string;
  data: T;
  revision: number;
  global_revision: number | null;
  session_id: string;
}

export interface AssignPolicy {
  maxRetries?: number;
  timeout?: number;
  priority?: number;
}

export interface HookInput {
  kind: string;
  hash: string;
}

export interface AssignInput<TArgs = unknown> {
  args: TArgs;
  policy?: AssignPolicy;
  dependency?: string;
  resolution?: string;
  implementation?: string;
  agent?: string;
  actionHash?: string;
  method?: string;
  interface?: string;
  hooks?: HookInput[];
  reference?: string;
  parent?: string;
  cached?: boolean;
  log?: boolean;
  capture?: boolean;
  ephemeral?: boolean;
  dependencies?: Record<string, unknown>;
  isHook?: boolean;
  step?: boolean;
}

export interface AssignOptions {
  notify?: boolean;
  policy?: AssignPolicy;
  agent?: string;
  reference?: string;
  parent?: string;
  cached?: boolean;
  log?: boolean;
  capture?: boolean;
  ephemeral?: boolean;
  hooks?: HookInput[];
  step?: boolean;
}

export interface TaskUpdate {
  task_id: string;
  status?: TaskStatus;
  result?: unknown;
  error?: string;
  progress?: number;
}

export interface AssignResponse {
  task_id: string;
  status: TaskStatus;
}

export interface RevisedStateSnapshot<T = unknown> {
  value: T;
  revision: number;
}

export type RevisedStatesSnapshotMap = Record<string, RevisedStateSnapshot>;

export interface StateView<T = unknown> {
  interface: string;
  name: string;
  initialized: boolean;
  local_revision: number;
  value: T | null;
}

export interface StateCollectionResponse<T = unknown> {
  current_session: string | null;
  current_global_revision: number | null;
  count: number;
  states: Record<string, StateView<T>>;
  recent_patches: RetrieverPatchEventResponse[];
}

export interface StateCheckoutResponse<T = unknown> {
  current_session: string | null;
  current_global_revision: number | null;
  count: number;
  states: Record<string, StateView<T>>;
  recent_patches: RetrieverPatchEventResponse[];
}

export interface RetrieverPatchEventResponse {
  timepoint: string;
  state_id: string;
  global_current_rev: number;
  global_future_rev: number;
  correlation_id: string;
  session_id: string;
  patch: unknown;
}

export interface StateSegmentsResponse {
  from_global_revision: number;
  to_global_revision: number;
  patches: RetrieverPatchEventResponse[];
}

export interface LockView {
  interface: string;
  key: string;
  task_id: string | null;
}

export interface LockCollectionResponse {
  count: number;
  locks: Record<string, LockView>;
}

export type LogLevel = "DEBUG" | "INFO" | "ERROR" | "WARN" | "CRITICAL";

export const TaskEventType = {
  REGISTER: "REGISTER",
  LOG: "LOG",
  PROGRESS: "PROGRESS",
  STARTED: "STARTED",
  COMPLETED: "COMPLETED",
  YIELD: "YIELD",
  FAILED: "FAILED",
  PAUSED: "PAUSED",
  CRITICAL: "CRITICAL",
  RESUMED: "RESUMED",
  CANCELLED: "CANCELLED",
  APP_CANCELLED: "APP_CANCELLED",
  INTERRUPTED: "INTERRUPTED",
  HEARTBEAT_ANSWER: "HEARTBEAT_ANSWER",
} as const;

export type TaskEventType = (typeof TaskEventType)[keyof typeof TaskEventType];

export const StateEventType = {
  STATE_UPDATE: "STATE_UPDATE",
  STATE_PATCH: "STATE_PATCH",
} as const;

export type StateEventType =
  (typeof StateEventType)[keyof typeof StateEventType];

export const LockEventType = {
  LOCK: "LOCK",
  UNLOCK: "UNLOCK",
} as const;

export type LockEventType = (typeof LockEventType)[keyof typeof LockEventType];

export const FromAgentMessageType = TaskEventType;
export type FromAgentMessageType = TaskEventType;

export interface BaseMessage {
  id: string;
  type: string;
}

export interface LogEvent extends BaseMessage {
  type: typeof TaskEventType.LOG;
  task: string;
  message: string;
  level: LogLevel;
}

export interface ProgressEvent extends BaseMessage {
  type: typeof TaskEventType.PROGRESS;
  task: string;
  progress?: number;
  message?: string;
}

export interface StartedEvent extends BaseMessage {
  type: typeof TaskEventType.STARTED;
  task: string;
}

export interface YieldEvent extends BaseMessage {
  type: typeof TaskEventType.YIELD;
  task: string;
  returns?: Record<string, unknown>;
}

export interface CompletedEvent extends BaseMessage {
  type: typeof TaskEventType.COMPLETED;
  task: string;
  returns?: Record<string, unknown>;
}

export interface FailedEvent extends BaseMessage {
  type: typeof TaskEventType.FAILED;
  task: string;
  error: string;
}

export interface CriticalEvent extends BaseMessage {
  type: typeof TaskEventType.CRITICAL;
  task: string;
  error: string;
}

export interface PausedEvent extends BaseMessage {
  type: typeof TaskEventType.PAUSED;
  task: string;
}

export interface ResumedEvent extends BaseMessage {
  type: typeof TaskEventType.RESUMED;
  task: string;
}

export interface CancelledEvent extends BaseMessage {
  type: typeof TaskEventType.CANCELLED;
  task: string;
}

export interface InterruptedEvent extends BaseMessage {
  type: typeof TaskEventType.INTERRUPTED;
  task: string;
}

export interface HeartbeatAnswerEvent extends BaseMessage {
  type: typeof TaskEventType.HEARTBEAT_ANSWER;
}

export interface RegisterMessage extends BaseMessage {
  type: typeof TaskEventType.REGISTER;
  instance_id: string;
  token: string;
}

export interface WebSocketInitMessage extends BaseMessage {
  type: "INIT";
  tasks: TaskCollectionResponse;
  states: StateCollectionResponse;
  locks: LockCollectionResponse;
}

export interface StateUpdateEvent {
  type: typeof StateEventType.STATE_UPDATE;
  state: string;
  value: unknown;
}

export interface EnvelopPatch {
  op: "add" | "remove" | "replace" | "move" | "copy" | "test";
  path: string;
  value?: unknown;
  old_value?: string;
}

export interface Envelope {
  state_name: string;
  rev: number;
  base_rev: number;
  ts: number;
  patches: EnvelopPatch[];
}

export interface StatePatchEvent {
  type: typeof StateEventType.STATE_PATCH;
  session_id: string;
  global_rev: number;
  state_name: string;
  ts: number;
  op: "add" | "remove" | "replace" | "move" | "copy";
  path: string;
  value?: unknown;
  old_value?: string;
  task_id?: string;
}

export interface LockEvent {
  type: typeof LockEventType.LOCK;
  key: string;
  task: string;
}

export interface UnlockEvent {
  type: typeof LockEventType.UNLOCK;
  key: string;
}

export type TaskEvent =
  | WebSocketInitMessage
  | LogEvent
  | ProgressEvent
  | StartedEvent
  | YieldEvent
  | CompletedEvent
  | FailedEvent
  | CriticalEvent
  | PausedEvent
  | ResumedEvent
  | CancelledEvent
  | LockEvent
  | UnlockEvent
  | InterruptedEvent
  | HeartbeatAnswerEvent
  | RegisterMessage;

export type StateEvent = StateUpdateEvent | StatePatchEvent;
export type LockEventMessage = LockEvent | UnlockEvent;

export type FromAgentMessage =
  | TaskEvent
  | StateEvent
  | LockEventMessage
  | StateUpdateEvent
  | StatePatchEvent;

export interface WebSocketSubscriptionInit {
  type?: string | null;
  /** Credential for the handshake; the websocket's stand-in for an auth header. */
  token?: string | null;
  action_keys?: string[] | null;
  state_keys?: string[] | null;
  lock_keys?: string[] | null;
  state_update_intervals?: Record<string, number> | null;
}

export type StateTransportMessage = StateEvent;
export type LockTransportMessage = LockEventMessage;
export type TaskTransportMessage = TaskEvent;

export interface TransportSocketConnectionState {
  isConnected: boolean;
  isReconnecting: boolean;
  isUnconnectable: boolean;
  reconnectAttempt: number;
}

export interface TransportMessageSubscription {
  unsubscribe: () => void;
}

export type SessionBoundaries = {
  sessionStart: Date;
  sessionEnd: Date;
  startRevision: number;
  endRevision: number;
  sessionId: string;
};

export type WebSocketMessage = FromAgentMessage;

export interface TransportConfig {
  apiEndpoint: string;
  wsEndpoint?: string;
  instanceId: string;
  appStateUpdateIntervals?: Partial<
    Record<string, Partial<Record<string, number>>>
  >;
  reconnect?: {
    maxAttempts?: number;
    initialDelay?: number;
    maxDelay?: number;
    backoffMultiplier?: number;
  };
  pingInterval?: number;
  appEndpoints?: Partial<
    Record<
      string,
      {
        apiEndpoint: string;
        wsEndpoint?: string;
      }
    >
  >;
}

export interface TransportContextValue {
  apiEndpoint: string;
  apps: AppsDefinition;
  wsUrl: string;
  instanceId: string;
  pingInterval: number;
  reconnect: Required<NonNullable<TransportConfig["reconnect"]>>;
  assignAction: <TArgs>(
    appKey: AppKey,
    actionName: string,
    args: TArgs,
    options?: AssignOptions,
  ) => Promise<AssignResponse>;
  fetchTask: <TArgs = unknown, TReturn = unknown>(
    appKey: AppKey,
    taskId: string,
  ) => Promise<Task<TArgs, TReturn>>;
  fetchSessionBoundaries: (
    appKey: AppKey,
    sessionId: string,
  ) => Promise<SessionBoundaries>;
  fetchActiveSessionBoundaries: (appKey: AppKey) => Promise<SessionBoundaries>;
  cancelTaskRequest: (appKey: AppKey, taskId: string) => Promise<void>;
  pauseTaskRequest: (appKey: AppKey, taskId: string) => Promise<void>;
  unpauseTaskRequest: (appKey: AppKey, taskId: string) => Promise<void>;
  stepTaskRequest: (appKey: AppKey, taskId: string) => Promise<void>;
  fetchState: <T = unknown>(
    appKey: AppKey,
    stateName: string,
  ) => Promise<StateView<T>>;
  fetchAll: <T = unknown>(
    appKey: AppKey,
    stateKeys?: string[],
  ) => Promise<StateCollectionResponse<T>>;
  fetchStateCheckout: (
    appKey: AppKey,
    globalRevisionId: string | number,
    stateKeys: string[],
  ) => Promise<StateCheckoutResponse>;
  fetchStateSegments: (
    appKey: AppKey,
    fromGlobalRevisionId: string | number,
    toGlobalRevisionId: string | number,
    stateKeys: string[],
  ) => Promise<StateSegmentsResponse>;
  fetchLocks: (appKey: AppKey) => Promise<Record<string, { task_id: string }>>;
  getApp: (appKey: AppKey) => AppDefinition;
  getEndpoints: (appKey: AppKey) => {
    apiEndpoint: string;
    wsUrl: string;
  };
  subscribeToMessages: (options: {
    appKey: AppKey;
    listener: (message: FromAgentMessage) => void;
  }) => TransportMessageSubscription;
  subscribeToConnectionState: (
    appKey: AppKey,
    listener: (state: TransportSocketConnectionState) => void,
  ) => () => void;
  reconnectSocket: (appKey: AppKey) => void;
  disconnectSocket: (appKey: AppKey) => void;
}

export interface TaskContextValue {
  isConnected: boolean;
  isReconnecting: boolean;
  reconnectAttempt: number;
  apiEndpoint: string;
  tasks: Map<string, Task>;
  createReference: () => string;
  assign: <TArgs, TReturn>(
    appKey: AppKey,
    actionName: string,
    args: TArgs,
    options?: AssignOptions,
  ) => Promise<Task<TArgs, TReturn>>;
  getTask: <TArgs = unknown, TReturn = unknown>(
    appKey: AppKey,
    taskId: string,
  ) => Promise<Task<TArgs, TReturn>>;
  getCachedTask: (taskId: string, appKey: AppKey) => Task | undefined;
  cancelTask: (appKey: AppKey, taskId: string) => Promise<void>;
  pauseTask: (appKey: AppKey, taskId: string) => Promise<void>;
  unpauseTask: (appKey: AppKey, taskId: string) => Promise<void>;
  stepTask: (appKey: AppKey, taskId: string) => Promise<void>;
  subscribeToTask: (
    taskId: string,
    appKey: AppKey,
    callback: (task: Task) => void,
  ) => () => void;
  waitForTask: <TArgs = unknown, TReturn = unknown>(
    appKey: AppKey,
    taskId: string,
  ) => Promise<Task<TArgs, TReturn>>;
  reconnect: (appKey: AppKey) => void;
  disconnect: (appKey: AppKey) => void;
}

export type ActionContextValue = TaskContextValue;
