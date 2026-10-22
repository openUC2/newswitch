/**
 * The layers of the stage scene as bloks: each draws one part of the 3D scene
 * from the app's live state, inside a `StageScene`.
 */
import type * as React from "react";
import * as z from "zod";
import { RectangleDrawer } from "@/components/stage/interactions/RectangleDrawer";
import { StagePositioner } from "@/components/stage/interactions/StagePositioner";
import { FramesPlane } from "@/components/stage/planes/FramesPlane";
import { ImagesPlane } from "@/components/stage/planes/ImagesPlane";
import { CurrentFrameLightPathPlane } from "@/components/stage/planes/LightPathStatePlane";
import { LivesPlane } from "@/components/stage/planes/LivesPlane";
import { StageAxis } from "@/components/stage/planes/StageAxis";
import { StagePlane } from "@/components/stage/planes/StagePlane";
import { CurrentLightPathPlane } from "@/components/stage/planes/lightpath/LightPathPlane";
import {
  createBlokComponent,
  type BlokComponentDefinition,
} from "@/lib/blok/renderer/runtime";

const layerBlok = (
  name: string,
  description: string,
  Layer: React.ComponentType,
): BlokComponentDefinition =>
  createBlokComponent(
    {
      name,
      placement: { context: "scene", downstreamOf: ["StageScene"] },
      schema: z.object({}).describe(description),
    },
    () => <Layer />,
  );

export const sceneBlokComponents: BlokComponentDefinition[] = [
  layerBlok("StageAxis", "The stage's axes and travel limits.", StageAxis),
  layerBlok(
    "StagePlane",
    "The stage at its current position (hidden in meta mode).",
    StagePlane,
  ),
  layerBlok(
    "FramesLayer",
    "The acquired frames, placed where they were taken.",
    FramesPlane,
  ),
  layerBlok(
    "ImagesLayer",
    "The captured images, placed where they were taken.",
    ImagesPlane,
  ),
  layerBlok(
    "LivesLayer",
    "The live streams of the acquiring detectors.",
    LivesPlane,
  ),
  layerBlok(
    "LightPathLayer",
    "The microscope's current light path.",
    CurrentLightPathPlane,
  ),
  layerBlok(
    "FrameLightPathLayer",
    "The light path the selected frame was taken with.",
    CurrentFrameLightPathPlane,
  ),
  layerBlok(
    "StagePositioner",
    "In move mode (hold M), click the scene to move the stage there.",
    StagePositioner,
  ),
  layerBlok(
    "RectangleDrawer",
    "In scan mode (hold D), draw a rectangle to define a scan region.",
    RectangleDrawer,
  ),
];
