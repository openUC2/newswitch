import { CameraMatrixSync } from "@/components/stage/CameraMatrixSync";
import { CameraController } from "@/components/stage/cameras/CameraController";
import { KeyboardModeController } from "@/components/stage/controllers/KeyboardModeController";
import { SceneWrapper } from "@/components/stage/Expanse";
import { SceneOverlay } from "@/components/stage/overlays/SceneOverlay";
import { PanelProvider } from "@/components/stage/PanelProvider";
import { FramePanel } from "@/components/stage/panels/FramePanel";
import { KubeStatePanel } from "@/components/stage/panels/KubeStatePanel";
import { CurrentLightPathPlane } from "@/components/stage/planes/lightpath/LightPathPlane";

export function ReplayPage() {
  return (
    <div className="h-full bg-background text-foreground dark w-full overflow-hidden">
      <PanelProvider>
        <KeyboardModeController />
        <SceneWrapper>
          <color attach="background" args={["#020617"]} />
          <ambientLight intensity={0.7} />
          <pointLight position={[100, 100, 100]} />

          {/* The Camera Matrix Sync ensures that we can access the view matrix outside in html world */}
          <CameraMatrixSync />

          <CurrentLightPathPlane />

          <CameraController />
        </SceneWrapper>

        <KubeStatePanel />

        <FramePanel />

        <SceneOverlay />
      </PanelProvider>
    </div>
  );
}
