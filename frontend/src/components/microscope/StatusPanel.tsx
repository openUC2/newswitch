import { Badge } from "@/components/ui/badge";
import {
  useDetectorState,
  useMoveState,
  useSourceState,
  useSwapState,
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
  const { data: detectors, loading: detectorsLoading } = useDetectorState({
    subscribe: true,
  });
  const { data: moves, loading: movesLoading } = useMoveState({
    subscribe: true,
  });
  const { data: sources, loading: sourcesLoading } = useSourceState({
    subscribe: true,
  });
  const { data: swaps, loading: swapsLoading } = useSwapState({
    subscribe: true,
  });

  return (
    <div className="flex items-center gap-1.5">
      <StatusBadge
        label={t("microscope.cameraShort")}
        isLoading={detectorsLoading}
        isConnected={!!detectors}
      />
      <StatusBadge
        label={t("microscope.stageShort")}
        isLoading={movesLoading}
        isConnected={!!moves}
      />
      <StatusBadge
        label={t("microscope.lightShort")}
        isLoading={sourcesLoading}
        isConnected={!!sources}
      />
      <StatusBadge
        label={t("microscope.objectiveShort")}
        isLoading={swapsLoading}
        isConnected={!!swaps}
      />
    </div>
  );
}
