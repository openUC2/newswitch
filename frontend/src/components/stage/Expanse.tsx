import type { ReactNode } from "react";
import { useDetectorState } from "@/apps/default/hooks/states";
import { Canvas } from "@react-three/fiber";
import { CameraMatrixSync } from "./CameraMatrixSync";
import { CameraController } from "./cameras/CameraController";
import { KeyboardModeController } from "./controllers/KeyboardModeController";
import { RectangleDrawer } from "./interactions/RectangleDrawer";
import { StagePositioner } from "./interactions/StagePositioner";
import { DebugOverlay } from "./overlays/DebugOverlay";
import { SceneOverlay } from "./overlays/SceneOverlay";
import { PanelProvider } from "./PanelProvider";
import { FramePanel } from "./panels/FramePanel";
import { ImageMetadataPanel } from "./panels/ImageMetadata";
import { ElementPanel } from "./panels/ElementPanel";
import { ScanRegionPanel } from "./panels/ScanRegionPanel";
import { FramesPlane } from "./planes/FramesPlane";
import { ImagesPlane } from "./planes/ImagesPlane";
import { LivesPlane } from "./planes/LivesPlane";
import { StageAxis } from "./planes/StageAxis";
import { StagePlane } from "./planes/StagePlane";
import {
  CurrentFrameLightPathPlane,
  CurrentLightPathPlane,
} from "./planes/lightpath/LightPathPlane";

export const SceneWrapper = ({ children }: { children: ReactNode }) => {
  return <Canvas>{children}</Canvas>;
};

export const Expanse = () => {
  useDetectorState({ subscribe: true });

  return (
    <div className="relative h-full w-full overflow-hidden rounded-lg bg-black">
      <PanelProvider>
        <KeyboardModeController />
        <SceneWrapper>
          <color attach="background" args={["#020617"]} />
          <ambientLight intensity={0.7} />
          <pointLight position={[100, 100, 100]} />

          {/* The Camera Matrix Sync ensures that we can access the view matrix outside in html world */}
          <CameraMatrixSync />

          <CurrentFrameLightPathPlane />

          <StageAxis />

          <FramesPlane />

          <StagePlane />

          <CameraController />

          {/* The Live Video Feed */}
          <LivesPlane />

          <CurrentLightPathPlane />

          <ImagesPlane />

          <StagePositioner />
          <RectangleDrawer />
        </SceneWrapper>

        <ScanRegionPanel />
        <ImageMetadataPanel />
        <ElementPanel />

        <FramePanel />

        <SceneOverlay />
        <DebugOverlay />
      </PanelProvider>
    </div>
  );
};
