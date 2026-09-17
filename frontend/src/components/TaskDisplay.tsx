import { Button } from "./ui/button";
import { Progress } from "./ui/progress";
import { useCancelTask } from "@/apps/default/hooks/useCancelTask";
import { useResumeTask } from "@/apps/default/hooks/useResumeTask";
import { usePauseTask } from "@/apps/default/hooks/usePauseTask";
import { useTaskStore } from "@/apps/default/hooks/useTaskStore";
import { selectTask } from "@/lib/rekuest/task/store";
import { useTranslation } from "react-i18next";

export const ProgressDisplay = (props: {
  activeTaskId: string | null | undefined;
}) => {
  const { t } = useTranslation();
  const activeTaskId = props.activeTaskId;

  // Use the built-in selector which safely resolves both local references and server IDs
  const task = useTaskStore(
    activeTaskId ? selectTask(activeTaskId) : () => undefined,
  );

  const cancel = useCancelTask();
  const resume = useResumeTask();
  const pause = usePauseTask();

  // 1. No active lock at all
  if (!activeTaskId) return null;

  // 2. Lock exists, but the task is not in our local store (initiated by another user/app)
  if (!task) {
    return (
      <div className="flex items-center justify-between text-muted-foreground text-sm p-3 bg-muted/50 rounded-lg">
        <span>{t("microscope.anotherAppControlsStage")}</span>
        <Button
          variant="outline"
          size="sm"
          onClick={() => cancel(activeTaskId)}
        >
          {t("common.cancel")}
        </Button>
      </div>
    );
  }

  // 3. Lock exists AND the task was initiated locally (we have progress and status)
  return (
    <div className="space-y-2 p-3 bg-muted/50 rounded-lg">
      <div className="flex items-center justify-between text-sm">
        <span className="text-muted-foreground">
          {t("microscope.movingStage")}
        </span>
        {task.progress !== null && task.progress !== undefined && (
          <span className="font-mono font-semibold">
            {Math.round(task.progress)}%
          </span>
        )}
      </div>
      <Progress value={task.progress ?? 0} className="h-1.5" />
      <div className="flex flex-row w-full gap-2">
        <Button
          variant="outline"
          size="sm"
          className="flex-1"
          onClick={() => cancel(activeTaskId)}
        >
          {t("common.cancel")}
        </Button>
        {task.status === "paused" ? (
          <Button
            variant="outline"
            size="sm"
            className="flex-1 animate-pulse"
            onClick={() => resume(activeTaskId)}
          >
            {t("microscope.resume")}
          </Button>
        ) : (
          <Button
            variant="destructive"
            size="sm"
            className="flex-1"
            onClick={() => pause(activeTaskId)}
          >
            {t("microscope.pause")}
          </Button>
        )}
      </div>
    </div>
  );
};
