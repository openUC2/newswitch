import { createContext, useContext } from "react";
import type { TaskContextValue } from "@/lib/arkitekt/transport/types";

export const TaskContext = createContext<TaskContextValue | null>(null);

export function useTaskContext(): TaskContextValue {
  const context = useContext(TaskContext);

  if (!context) {
    throw new Error("useTaskContext must be used within a BundleProvider");
  }

  return context;
}
