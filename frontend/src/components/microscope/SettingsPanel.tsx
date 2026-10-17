import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Separator } from "@/components/ui/separator";
import {
  useClearExpanse,
  useStartLiveView,
  useStopLiveView,
} from "@/apps/default/hooks/actions";
import { useCameraState, useObjectiveState } from "@/apps/default/hooks/states";
import { useCaptureAndDownload } from "@/hooks/useCaptureAndDownload";
import { cn } from "@/lib/utils";
import {
  Camera,
  ChevronDown,
  Download,
  Filter,
  Play,
  RefreshCcw,
  Settings2,
  Square,
  Sun,
  Target,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { CameraControl } from "./CameraControl";
import { FilterBankControl } from "./FilterBankControl";
import { IlluminationControl } from "./IlluminationControl";
import { ObjectiveControl } from "./ObjectiveControl";

interface SettingsSectionProps {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
  badge?: string;
}

function SettingsSection({
  title,
  icon,
  children,
  defaultOpen = true,
  badge,
}: SettingsSectionProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger className="flex items-center justify-between w-full py-2 px-3 hover:bg-accent rounded-md">
        <div className="flex items-center gap-2 text-sm font-medium">
          {icon}
          {title}
          {badge && (
            <Badge variant="secondary" className="text-xs ml-2">
              {badge}
            </Badge>
          )}
        </div>
        <ChevronDown
          className={cn("h-4 w-4 transition-transform", isOpen && "rotate-180")}
        />
      </CollapsibleTrigger>
      <CollapsibleContent className="px-3 pb-3 space-y-3">
        {children}
      </CollapsibleContent>
    </Collapsible>
  );
}

export function SettingsPanel() {
  const { t } = useTranslation();
  const { data: cameraState } = useCameraState({ subscribe: true });
  const { data: objectiveState } = useObjectiveState({ subscribe: true });
  // Live view and capture controls
  const {
    assign: startLiveView,
    isLoading: isStarting,
    isLocked: isStartLocked,
  } = useStartLiveView();
  const {
    assign: stopLiveView,
    isLoading: isStopping,
    isLocked: isStopLocked,
  } = useStopLiveView();
  const {
    capture,
    isCapturing,
    isDownloading,
    isLocked: isCaptureLocked,
  } = useCaptureAndDownload();

  const { call: reset } = useClearExpanse();

  const isLive = cameraState?.is_acquiring ?? false;

  return (
    <div className="h-full flex flex-col">
      <div className="p-3 border-b space-y-2">
        <h2 className="text-sm font-semibold flex items-center gap-2">
          <Settings2 className="h-4 w-4" />
          {t("microscope.settings")}
        </h2>

        {/* Acquisition Controls */}
        <div className="flex gap-1.5">
          <Button
            variant={isLive ? "destructive" : "default"}
            size="sm"
            onClick={async () => {
              if (isLive) {
                await stopLiveView({});
              } else {
                await startLiveView({});
              }
            }}
            disabled={isStarting || isStopping || isStartLocked || isStopLocked}
            className="gap-1.5 flex-1"
          >
            {isLive ? (
              <>
                <Square className="h-3 w-3" />
                {t("microscope.stop")}
              </>
            ) : (
              <>
                <Play className="h-3 w-3" />
                {t("microscope.live")}
              </>
            )}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={async () => await capture()}
            disabled={isCapturing || isDownloading || isCaptureLocked}
            className="gap-1.5 flex-1"
          >
            {isDownloading ? (
              <Download className="h-3 w-3 animate-bounce" />
            ) : (
              <Camera className="h-3 w-3" />
            )}
            {isDownloading ? t("common.save") : t("microscope.snap")}
          </Button>
          <Button
            variant="secondary"
            size="icon"
            onClick={async () => await reset({})}
            className="gap-1.5 flex-1"
          >
            <RefreshCcw className="h-3 w-3" />
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Camera Settings */}
        <SettingsSection
          title={t("microscope.camera")}
          icon={<Camera className="h-4 w-4" />}
        >
          <CameraControl />
        </SettingsSection>

        <Separator />

        {/* Illumination Settings */}
        <SettingsSection
          title={t("microscope.illumination")}
          icon={<Sun className="h-4 w-4" />}
        >
          <IlluminationControl />
        </SettingsSection>
        {/* Illumination Settings */}
        <SettingsSection
          title={t("microscope.filters")}
          icon={<Filter className="h-4 w-4" />}
        >
          <FilterBankControl />
        </SettingsSection>

        <Separator />

        {/* Objective Settings */}
        <SettingsSection
          title={t("microscope.objective")}
          icon={<Target className="h-4 w-4" />}
          badge={
            objectiveState?.slot
              ? t("common.slot", { slot: objectiveState.slot })
              : undefined
          }
        >
          <ObjectiveControl />
        </SettingsSection>

        <Separator />
      </div>
    </div>
  );
}
