import { z, ZodType } from "zod";
import type {
  AssignOptions,
  Task,
  TaskStatus,
} from "@/lib/arkitekt/transport/types";

export interface ActionDefinition<
  TArgs,
  TReturn,
  TAppKey extends string = string,
> {
  name: string;
  appKey: TAppKey;
  description?: string;
  // TArgs is the schema's INPUT, not its output: callers hand-build args and useAction
  // parses them (`argsSchema.safeParse(args)`) before sending `parsed.data` to the wire.
  // Typing this as ZodType<TArgs> would pin TArgs to the *output* - and since the generated
  // model schemas are `.brand()`ed, that output is unconstructible by hand.
  argsSchema: ZodType<unknown, TArgs>;
  returnSchema: ZodType<TReturn>;
  lockKeys: string[];
}

export type UseAppTaskMutationResult = (taskId: string) => Promise<void>;

export interface UseActionOptions {
  autoSubscribe?: boolean;
  onStatusChange?: (status: TaskStatus, task: Task) => void;
  onComplete?: <TReturn>(result: TReturn, task: Task) => void;
  onError?: (error: string, task: Task) => void;
  onProgress?: (progress: number, task: Task) => void;
}

export interface UseActionResult<TArgs, TReturn> {
  call: (args: TArgs, options?: AssignOptions) => Promise<TReturn>;
  assign: (
    args: TArgs,
    options?: AssignOptions,
  ) => Promise<Task<TArgs, TReturn>>;
  // The currently-tracked task. useAction already derives status/result/progress from it;
  // consumers need the task itself for its id (pause/resume take a task id).
  task: Task<TArgs, TReturn> | null;
  status: TaskStatus | null;
  result: TReturn | null;
  error: string | null;
  progress: number | null;
  isLive: boolean;
  isLoading: boolean;
  isLocked: boolean;
  lockedBy: string | null;
  lockedByKey: string | null;
  validationError: z.ZodError | null;
  refresh: () => Promise<void>;
  cancel: () => Promise<void>;
  clear: () => void;
}

export type UseTransportActionOptions = UseActionOptions;
export type UseTransportActionResult<TArgs, TReturn> = UseActionResult<
  TArgs,
  TReturn
>;
