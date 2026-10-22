import { useTaskStore } from "@/apps/default/hooks/useTaskStore";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useLock } from "@/hooks/useLock";
import { selectTask } from "@/lib/arkitekt/task/store";
import { Bug } from "lucide-react";

interface SyncKeyDebugProps {
  syncKey: string;
  appKey: string;
}

export function SyncKeyDebug({ syncKey, appKey }: SyncKeyDebugProps) {
  const syncKeyState = useLock({ key: syncKey, appKey });
  const task = useTaskStore(
    syncKeyState?.lockingTaskId
      ? selectTask(syncKeyState.lockingTaskId)
      : () => undefined,
  );

  return (
    <Card className="border-dashed border-orange-500/50 bg-orange-50/50 dark:bg-orange-950/20">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm flex items-center gap-2 text-orange-700 dark:text-orange-400">
          <Bug className="h-4 w-4" />
          Debug: SyncKey "{syncKey}"
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-xs font-mono">
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">Task ID:</span>
          <span className="font-semibold truncate max-w-[150px]">
            {syncKeyState?.lockingTaskId ?? "—"}
          </span>
        </div>

        {task && (
          <>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Status:</span>
              <Badge
                variant={
                  task.status === "completed"
                    ? "default"
                    : task.status === "failed"
                      ? "destructive"
                      : task.status === "running"
                        ? "secondary"
                        : "outline"
                }
                className="text-xs"
              >
                {task.status}
              </Badge>
            </div>

            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Action:</span>
              <span className="font-semibold">{task.action}</span>
            </div>

            {task.progress !== undefined && task.progress !== null && (
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Progress:</span>
                <span className="font-semibold">{task.progress}%</span>
              </div>
            )}

            {task.progressMessage && (
              <div className="flex flex-col gap-1">
                <span className="text-muted-foreground">Message:</span>
                <span className="text-xs break-all">
                  {task.progressMessage}
                </span>
              </div>
            )}

            {task.error && (
              <div className="flex flex-col gap-1">
                <span className="text-muted-foreground text-destructive">
                  Error:
                </span>
                <span className="text-xs break-all text-destructive">
                  {task.error}
                </span>
              </div>
            )}

            <div className="pt-2 border-t border-orange-200 dark:border-orange-800">
              <div className="text-[10px] text-muted-foreground">
                Created: {task.createdAt.toLocaleTimeString()}
              </div>
              <div className="text-[10px] text-muted-foreground">
                Updated: {task.updatedAt.toLocaleTimeString()}
              </div>
            </div>
          </>
        )}

        {!task && syncKeyState?.lockingTaskId && (
          <div className="text-xs text-destructive">
            Task ID exists but task not found in store TODO: Implement this
          </div>
        )}

        {!syncKeyState && (
          <div className="text-xs text-muted-foreground italic">
            No active task locking this action
          </div>
        )}
      </CardContent>
    </Card>
  );
}
