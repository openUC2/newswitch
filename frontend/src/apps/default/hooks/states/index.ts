import type { StateDefinition } from '@/lib/arkitekt/state';
import { AutofocusStateDefinition } from './AutofocusState';
import { CalibrationStateDefinition } from './CalibrationState';
import { DetectorStateDefinition } from './DetectorState';
import { ExpanseStateDefinition } from './ExpanseState';
import { HookStateDefinition } from './HookState';
import { IoStateDefinition } from './IoState';
import { MountCalibrationStateDefinition } from './MountCalibrationState';
import { MoveStateDefinition } from './MoveState';
import { OpticsStateDefinition } from './OpticsState';
import { SourceStateDefinition } from './SourceState';
import { SpaceStateDefinition } from './SpaceState';
import { SwapStateDefinition } from './SwapState';
import { TuneStateDefinition } from './TuneState';
import { Uc2StateDefinition } from './Uc2State';

export { createIndexedUnion } from './utils';
export {
  AutofocusStateSchema,
  AutofocusStateDefinition,
  useAutofocusState,
} from './AutofocusState';
export type { AutofocusState } from './AutofocusState';
export {
  CalibratedLightPathSchema,
  CalibratedMountSchema,
  CalibrationStateSchema,
  CalibrationStateDefinition,
  useCalibrationState,
} from './CalibrationState';
export type {
  CalibratedLightPath,
  CalibratedLightPathOutput,
  CalibratedMount,
  CalibratedMountOutput,
  CalibrationState,
} from './CalibrationState';
export {
  DetectorAxisSchema,
  DetectorSchema,
  DetectorStateSchema,
  DetectorStateDefinition,
  useDetectorState,
} from './DetectorState';
export type {
  DetectorAxis,
  DetectorAxisOutput,
  Detector,
  DetectorOutput,
  DetectorState,
} from './DetectorState';
export {
  LightPathSnapshotSchema,
  MetadataSchema,
  ImageSchema,
  ScaleSchema,
  ArrayMetadataSchema,
  FrameSchema,
  ExpanseStateSchema,
  ExpanseStateDefinition,
  useExpanseState,
} from './ExpanseState';
export type {
  LightPathSnapshot,
  LightPathSnapshotOutput,
  Metadata,
  MetadataOutput,
  Image,
  ImageOutput,
  Scale,
  ScaleOutput,
  ArrayMetadata,
  ArrayMetadataOutput,
  Frame,
  FrameOutput,
  ExpanseState,
} from './ExpanseState';
export {
  RegisteredHookSchema,
  HookStateSchema,
  HookStateDefinition,
  useHookState,
} from './HookState';
export type {
  RegisteredHook,
  RegisteredHookOutput,
  HookState,
} from './HookState';
export { IoStateSchema, IoStateDefinition, useIoState } from './IoState';
export type { IoState } from './IoState';
export {
  MeasuredMountSchema,
  MountCalibrationStateSchema,
  MountCalibrationStateDefinition,
  useMountCalibrationState,
} from './MountCalibrationState';
export type {
  MeasuredMount,
  MeasuredMountOutput,
  MountCalibrationState,
} from './MountCalibrationState';
export {
  MoveValueSchema,
  MoveStateSchema,
  MoveStateDefinition,
  useMoveState,
} from './MoveState';
export type { MoveValue, MoveValueOutput, MoveState } from './MoveState';
export {
  LightPathSchema,
  DetectorOpticsSchema,
  SourceOpticsSchema,
  ChannelSwapSchema,
  OpticalChannelSchema,
  OpticsStateSchema,
  OpticsStateDefinition,
  useOpticsState,
} from './OpticsState';
export type {
  LightPath,
  LightPathOutput,
  DetectorOptics,
  DetectorOpticsOutput,
  SourceOptics,
  SourceOpticsOutput,
  ChannelSwap,
  ChannelSwapOutput,
  OpticalChannel,
  OpticalChannelOutput,
  OpticsState,
} from './OpticsState';
export {
  LightSourceSchema,
  SourceStateSchema,
  SourceStateDefinition,
  useSourceState,
} from './SourceState';
export type {
  LightSource,
  LightSourceOutput,
  SourceState,
} from './SourceState';
export {
  AxisSchema,
  CoordinateSystemSchema,
  DimensionPartSchema,
  TransformationSchema,
  PlaceShapeSchema,
  HolderShapeSchema,
  SampleSpaceSchema,
  DetectorPlacementSchema,
  MeasuredPointSchema,
  SpaceStateSchema,
  SpaceStateDefinition,
  useSpaceState,
} from './SpaceState';
export type {
  Axis,
  AxisOutput,
  CoordinateSystem,
  CoordinateSystemOutput,
  DimensionPart,
  DimensionPartOutput,
  Transformation,
  TransformationOutput,
  PlaceShape,
  PlaceShapeOutput,
  HolderShape,
  HolderShapeOutput,
  SampleSpace,
  SampleSpaceOutput,
  DetectorPlacement,
  DetectorPlacementOutput,
  MeasuredPoint,
  MeasuredPointOutput,
  SpaceState,
} from './SpaceState';
export {
  SwapOptionSchema,
  SwapValueSchema,
  SwapStateSchema,
  SwapStateDefinition,
  useSwapState,
} from './SwapState';
export type {
  SwapOption,
  SwapOptionOutput,
  SwapValue,
  SwapValueOutput,
  SwapState,
} from './SwapState';
export {
  TuneValueSchema,
  TuneStateSchema,
  TuneStateDefinition,
  useTuneState,
} from './TuneState';
export type { TuneValue, TuneValueOutput, TuneState } from './TuneState';
export {
  Uc2NodeSchema,
  Uc2StateSchema,
  Uc2StateDefinition,
  useUc2State,
} from './Uc2State';
export type { Uc2Node, Uc2NodeOutput, Uc2State } from './Uc2State';

export const globalStateDefinition = {
  AutofocusState: AutofocusStateDefinition,
  CalibrationState: CalibrationStateDefinition,
  DetectorState: DetectorStateDefinition,
  ExpanseState: ExpanseStateDefinition,
  HookState: HookStateDefinition,
  IoState: IoStateDefinition,
  MountCalibrationState: MountCalibrationStateDefinition,
  MoveState: MoveStateDefinition,
  OpticsState: OpticsStateDefinition,
  SourceState: SourceStateDefinition,
  SpaceState: SpaceStateDefinition,
  SwapState: SwapStateDefinition,
  TuneState: TuneStateDefinition,
  Uc2State: Uc2StateDefinition,
} satisfies Record<string, StateDefinition<unknown>>;

type InferStateDefinition<TDefinition> =
  TDefinition extends StateDefinition<infer TState, string> ? TState : never;

export type GlobalStateDefinition = typeof globalStateDefinition;
export type GlobalStateKey = keyof GlobalStateDefinition;
export type GlobalStateShape = {
  [K in GlobalStateKey]: InferStateDefinition<GlobalStateDefinition[K]>;
};

export const globalStateKeys = Object.values(globalStateDefinition).map(
  (definition) => definition.key,
) as GlobalStateKey[];
export const globalStateDefintiion = globalStateDefinition;
