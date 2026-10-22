/**
 * The microscope's control panels as bloks.
 *
 * Each wraps an existing panel unchanged: the panel reads and changes the
 * microscope through the app's generated hooks, so a blok only places it.
 */
import type * as React from "react";
import * as z from "zod";
import {
  CameraControl,
  FilterBankControl,
  IlluminationControl,
  LatestImage,
  LiveView,
  MultidimensionalAcquisitionControl,
  ObjectiveControl,
  SettingsPanel,
  StageControl,
  StatusPanel,
} from "@/components/microscope";
import { BloksPanel } from "@/components/bloks/BloksPanel";
import { CalibrateLightPath } from "@/components/microscope/CalibrateLightPath";
import {
  createBlokComponent,
  useBlok,
  useValue,
  type BlokComponentDefinition,
} from "@/lib/blok/renderer/runtime";
import { classNameSchema } from "@/lib/blok/renderer/bloks/shared/schemas";
import { usePanelLocked } from "./locks";

/**
 * A blok placing `Panel` in a `div` that takes the blok's `className`. `actions` are
 * the backend actions the panel runs: while a lock one of them takes is held, the div
 * is marked `data-locked` (the `locked:` variant).
 */
const panelBlok = (
  name: string,
  description: string,
  Panel: React.ComponentType,
  actions: readonly string[] = [],
): BlokComponentDefinition =>
  createBlokComponent(
    {
      name,
      schema: z.object({ className: classNameSchema }).describe(description),
    },
    ({ component, schema }) => {
      const blok = useBlok(component, schema);
      const className = useValue(blok.className);
      const locked = usePanelLocked(actions);
      return (
        <div
          className={className}
          data-locked={locked ? "" : undefined}
          title={locked}
        >
          <Panel />
        </div>
      );
    },
  );

export const microscopeBlokComponents: BlokComponentDefinition[] = [
  panelBlok(
    "SettingsPanel",
    "The microscope's settings column: live view, capture, and the camera, filter, illumination and objective controls.",
    SettingsPanel,
    ["start_live_view", "stop_live_view", "capture_image", "clear_expanse"],
  ),
  panelBlok(
    "CameraControl",
    "Detectors: switch them on and off, set gain and exposure.",
    CameraControl,
    ["activate_detector", "deactivate_detector", "update_detector"],
  ),
  panelBlok(
    "IlluminationControl",
    "Illumination channels: switch them on and off, set intensity.",
    IlluminationControl,
    [
      "turn_on_illumination",
      "turn_off_illumination_channel",
      "set_illumination_intensity",
    ],
  ),
  panelBlok(
    "FilterBankControl",
    "The filter wheel: switch or toggle the active filter.",
    FilterBankControl,
    ["switch_filter", "toggle_filter"],
  ),
  panelBlok(
    "ObjectiveControl",
    "The objective turret: switch the active objective.",
    ObjectiveControl,
    ["switch_objective", "toggle_objective"],
  ),
  panelBlok(
    "StageControl",
    "Stage position and moves, with the move's progress.",
    StageControl,
    ["move_stage", "move_home"],
  ),
  panelBlok(
    "MultidimensionalAcquisitionControl",
    "The multidimensional acquisition form: timepoints, positions, stacks and channels; start, pause and resume.",
    MultidimensionalAcquisitionControl,
    ["acquire_multidimensional_acquisition"],
  ),
  panelBlok(
    "CalibrateLightPath",
    "Calibrate the light path (pixel sizes).",
    CalibrateLightPath,
    ["calibrate_light_path"],
  ),
  panelBlok(
    "StatusPanel",
    "Badges for the camera, stage, illumination and objective state.",
    StatusPanel,
  ),
  panelBlok("LiveView", "The live camera stream.", LiveView),
  panelBlok("LatestImage", "The most recently written image.", LatestImage),
  panelBlok(
    "BloksPanel",
    "Lists the other bloks the backend declares and opens one in a dialog.",
    BloksPanel,
  ),
];
