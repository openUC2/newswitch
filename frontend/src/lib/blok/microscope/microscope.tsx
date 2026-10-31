/**
 * The microscope's control panels as bloks.
 *
 * Each wraps an existing panel unchanged: the panel reads and changes the
 * microscope through the app's generated hooks, so a blok only places it.
 */
import type * as React from "react";
import * as z from "zod";
import {
  LatestImage,
  LiveView,
  AcquisitionControl,
  SettingsPanel,
  StatusPanel,
} from "@/components/microscope";
import { BloksPanel } from "@/components/bloks/BloksPanel";
import { CalibrateLightPath } from "@/components/microscope/CalibrateLightPath";
import { DetectorControl } from "@/components/microscope/DetectorControl";
import { MoveControl } from "@/components/microscope/MoveControl";
import { SourceControl } from "@/components/microscope/SourceControl";
import { SwapsControl } from "@/components/microscope/SwapsControl";
import { VariableControl } from "@/components/microscope/VariableControl";
import {
  createBlokComponent,
  useBlok,
  useValue,
  type BlokComponentDefinition,
} from "@arkitektio/bsx/renderer/runtime/index";
import { classNameSchema } from "@arkitektio/bsx/catalogs";
import { PAST_REASON, useIsLive, usePanelLocked } from "./locks";

/**
 * A blok placing `Panel` in a `div` that takes the blok's `className`. `actions` are
 * the backend actions the panel runs: while a lock one of them takes is held, the div
 * is marked `data-locked` (the `locked:` variant). A panel that runs actions cannot be
 * used in the past (replay): it is made `inert` then, so neither a click nor the
 * keyboard reaches its controls.
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
      const past = !useIsLive() && actions.length > 0;
      return (
        <div
          className={className}
          data-locked={locked ? "" : undefined}
          inert={past}
          title={past ? PAST_REASON : locked}
        >
          <Panel />
        </div>
      );
    },
  );

const VariableBlok = createBlokComponent(
  {
    name: "VariableControl",
    schema: z
      .object({
        name: z
          .string()
          .describe("The variable: stage.z, objective.slot, laser_488.power."),
        className: classNameSchema,
      })
      .describe(
        "The control of one variable, whatever it is, by its name in the description.",
      ),
  },
  ({ component, schema }) => {
    const blok = useBlok(component, schema);
    const name = useValue(blok.name) ?? "";
    const className = useValue(blok.className);
    const locked = usePanelLocked(["move_one", "swap", "tune"]);
    return (
      <div
        className={className}
        data-locked={locked ? "" : undefined}
        title={locked}
      >
        <VariableControl name={name} />
      </div>
    );
  },
);

const LiveViewBlok = createBlokComponent(
  {
    name: "LiveView",
    schema: z
      .object({
        detector: z
          .string()
          .optional()
          .describe(
            "Which detector to show; without one, a choice of those that are on.",
          ),
        className: classNameSchema,
      })
      .describe("The live stream of a detector."),
  },
  ({ component, schema }) => {
    const blok = useBlok(component, schema);
    const detector = useValue(blok.detector);
    const className = useValue(blok.className);
    return (
      <div className={className}>
        <LiveView detector={detector} />
      </div>
    );
  },
);

export const microscopeBlokComponents: BlokComponentDefinition[] = [
  VariableBlok,
  LiveViewBlok,
  panelBlok(
    "SettingsPanel",
    "The microscope's settings column: live view, capture, and the camera, filter, illumination and objective controls.",
    SettingsPanel,
    ["start_live_view", "stop_live_view", "capture_image", "clear_expanse"],
  ),
  panelBlok(
    "DetectorControl",
    "Detectors: switch them on and off, and tune whatever each can tune.",
    DetectorControl,
    ["activate_detector", "deactivate_detector", "tune"],
  ),
  panelBlok(
    "SourceControl",
    "Light sources: switch them on and off, set their power.",
    SourceControl,
    ["tune"],
  ),
  panelBlok(
    "SwapsControl",
    "Everything that is swapped: put another thing in place.",
    SwapsControl,
    ["swap"],
  ),
  panelBlok(
    "MoveControl",
    "Everything that moves, with the move's progress: a pad for what moves the view, up and down for what focuses it, when it is clear which those are.",
    MoveControl,
    ["move", "move_one", "move_home"],
  ),
  panelBlok(
    "AcquisitionControl",
    "An acquisition as a plan over what this microscope has: channels, positions, planes and times.",
    AcquisitionControl,
    ["acquire"],
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
  panelBlok("LatestImage", "The most recently written image.", LatestImage),
  panelBlok(
    "BloksPanel",
    "Lists the other bloks the backend declares and opens one in a dialog.",
    BloksPanel,
  ),
];
