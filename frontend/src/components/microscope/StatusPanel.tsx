import { Badge } from "@/components/ui/badge";
import {
  useCameraState,
  useIlluminationState,
  useObjectiveState,
  useStageState,
} from "@/apps/default/hooks/states";
import { CheckCircle2, RefreshCw, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";

function StatusBadge({
  label,
  isLoading,
  isConnected,
}: {
  label: string;
  isLoading: boolean;
  isConnected: boolean;
}) {
  return (
    <Badge
      variant={isLoading ? "outline" : isConnected ? "default" : "secondary"}
      className="gap-1 text-xs"
    >
      {isLoading ? (
        <RefreshCw className="h-2.5 w-2.5 animate-spin" />
      ) : isConnected ? (
        <CheckCircle2 className="h-2.5 w-2.5" />
      ) : (
        <XCircle className="h-2.5 w-2.5" />
      )}
      {label}
    </Badge>
  );
}

export function StatusPanel() {
  const { t } = useTranslation();
  const { data: camera, loading: cameraLoading } = useCameraState({
    subscribe: true,
  });
  const { data: stage, loading: stageLoading } = useStageState({
    subscribe: true,
  });
  const { data: illumination, loading: illuminationLoading } =
    useIlluminationState({ subscribe: true });
  const { data: objective, loading: objectiveLoading } = useObjectiveState({
    subscribe: true,
  });

  return (
    <div className="flex items-center gap-1.5">
      <StatusBadge
        label={t("microscope.cameraShort")}
        isLoading={cameraLoading}
        isConnected={!!camera}
      />
      <StatusBadge
        label={t("microscope.stageShort")}
        isLoading={stageLoading}
        isConnected={!!stage}
      />
      <StatusBadge
        label={t("microscope.lightShort")}
        isLoading={illuminationLoading}
        isConnected={!!illumination}
      />
      <StatusBadge
        label={t("microscope.objectiveShort")}
        isLoading={objectiveLoading}
        isConnected={!!objective}
      />
    </div>
  );
}
