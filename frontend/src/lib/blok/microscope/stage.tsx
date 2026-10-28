/**
 * The stage view as bloks: a `StageView` holds a `StageScene` (the 3D canvas,
 * whose children are scene layers) and the panels floating over it.
 *
 * Mirrors `Expanse`: the floating panels place themselves with the camera
 * matrix the scene publishes, so they and the scene share one `StageView`.
 */
import type * as React from "react";
import { useEffect } from "react";
import * as z from "zod";
import { useCameraState } from "@/apps/default/hooks/states";
import { CameraMatrixSync } from "@/components/stage/CameraMatrixSync";
import { CameraController } from "@/components/stage/cameras/CameraController";
import { KeyboardModeController } from "@/components/stage/controllers/KeyboardModeController";
import { SceneWrapper } from "@/components/stage/Expanse";
import { DebugOverlay } from "@/components/stage/overlays/DebugOverlay";
import { SceneOverlay } from "@/components/stage/overlays/SceneOverlay";
import { PanelProvider } from "@/components/stage/PanelProvider";
import { FramePanel } from "@/components/stage/panels/FramePanel";
import { ImageMetadataPanel } from "@/components/stage/panels/ImageMetadata";
import { KubeStatePanel } from "@/components/stage/panels/KubeStatePanel";
import { ScanRegionPanel } from "@/components/stage/panels/ScanRegionPanel";
import {
  BlokNodeErrorSurface,
  createBlokComponent,
  useBlok,
  useValue,
  type BlokComponentDefinition,
  type BlokNodeErrorProps,
} from "@arkitektio/bsx/renderer/runtime/index";
import { renderChildList } from "@arkitektio/bsx/renderer/bloks/shared/render";
import { childListSchema, classNameSchema } from "@arkitektio/bsx/catalogs";
import { cn } from "@/lib/utils";
import { useIsLive } from "./locks";

export const StageView = createBlokComponent(
  {
    name: "StageView",
    schema: z
      .object({
        children: childListSchema.describe(
          "A StageScene and the panels floating over it.",
        ),
        className: classNameSchema,
      })
      .describe(
        "The stage view: holds the 3D StageScene and the panels that float over it. Keyboard modes (D/E/M) apply while it is shown.",
      ),
  },
  ({ buildChild, component, schema }) => {
    const blok = useBlok(component, schema);
    const children = useValue(blok.children);
    const className = useValue(blok.className);
    // Keep the camera state live while the view is shown, as Expanse does.
    useCameraState({ subscribe: true });

    return (
      <div
        className={cn(
          "relative h-full w-full overflow-hidden rounded-lg bg-black",
          className,
        )}
      >
        <PanelProvider>
          <KeyboardModeController />
          {renderChildList(children, buildChild)}
        </PanelProvider>
      </div>
    );
  },
);

/** Inside the canvas nothing can render a `div`: a broken layer is logged and left out. */
const SceneNodeError = ({ componentId, title, detail }: BlokNodeErrorProps) => {
  useEffect(() => {
    console.error(`[blok] scene layer "${componentId}": ${title}`, detail);
  }, [componentId, title, detail]);
  return null;
};

export const StageScene = createBlokComponent(
  {
    name: "StageScene",
    placement: { childrenContext: "scene", downstreamOf: ["StageView"] },
    schema: z
      .object({
        children: childListSchema.describe(
          "Scene layers: StageAxis, StagePlane, FramesLayer, ImagesLayer, LivesLayer, LightPathLayer, FrameLightPathLayer, StagePositioner, RectangleDrawer.",
        ),
        background: z
          .string()
          .optional()
          .describe("Background color of the scene. Defaults to #020617."),
      })
      .describe(
        "The 3D stage scene. Brings its camera (orbit in 3D, map in 2D) and lights; its children are the layers drawn in it.",
      ),
  },
  ({ buildChild, component, schema }) => {
    const blok = useBlok(component, schema);
    const children = useValue(blok.children);
    const background = useValue(blok.background) ?? "#020617";

    return (
      <SceneWrapper>
        <BlokNodeErrorSurface.Provider value={SceneNodeError}>
          <color attach="background" args={[background]} />
          <ambientLight intensity={0.7} />
          <pointLight position={[100, 100, 100]} />
          {/* The floating panels position themselves with this matrix. */}
          <CameraMatrixSync />
          <CameraController />
          {renderChildList(children, buildChild)}
        </BlokNodeErrorSurface.Provider>
      </SceneWrapper>
    );
  },
);

/**
 * A panel floating over the scene; it places itself, so it takes no props. An
 * `interactive` one changes the microscope (starts a scan): it is not shown in the
 * past (replay), where nothing can be changed.
 */
const floaterBlok = (
  name: string,
  description: string,
  Floater: React.ComponentType,
  interactive = false,
): BlokComponentDefinition =>
  createBlokComponent(
    {
      name,
      placement: { downstreamOf: ["StageView"] },
      schema: z.object({}).describe(description),
    },
    () => {
      const live = useIsLive();
      return interactive && !live ? null : <Floater />;
    },
  );

export const stageBlokComponents: BlokComponentDefinition[] = [
  StageView,
  StageScene,
  floaterBlok(
    "ScanRegionPanel",
    "Edits the selected scan region and starts its scan.",
    ScanRegionPanel,
    true,
  ),
  floaterBlok(
    "ImageMetadataPanel",
    "Metadata of the selected image.",
    ImageMetadataPanel,
  ),
  floaterBlok(
    "KubeStatePanel",
    "Details of the selected light-path component (kube).",
    KubeStatePanel,
  ),
  floaterBlok("FramePanel", "Details of the selected frame.", FramePanel),
  floaterBlok(
    "SceneOverlay",
    "Toolbar over the scene: 2D/3D, interaction mode, debug, clear.",
    SceneOverlay,
  ),
  floaterBlok("DebugOverlay", "Debug tools over the scene.", DebugOverlay),
];
