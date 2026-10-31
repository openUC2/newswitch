import type { StateDefinition } from '@/lib/arkitekt/state';
import { AutofocusStateDefinition } from './AutofocusState';
import { CalibrationStateDefinition } from './CalibrationState';
import { DetectorStateDefinition } from './DetectorState';
import { ExpanseStateDefinition } from './ExpanseState';
import { HookStateDefinition } from './HookState';
import { IOStateDefinition } from './IOState';
import { MoveStateDefinition } from './MoveState';
import { OpticsStateDefinition } from './OpticsState';
import { SourceStateDefinition } from './SourceState';
import { SwapStateDefinition } from './SwapState';
import { TuneStateDefinition } from './TuneState';
import { UC2StateDefinition } from './UC2State';

export { createIndexedUnion } from './utils';
export {
  AutofocusStateSchema,
  AutofocusStateDefinition,
  useAutofocusState,
} from './AutofocusState';
export type { AutofocusState } from './AutofocusState';
export {
  CalibratedLightPathSchema,
  CalibrationStateSchema,
  CalibrationStateDefinition,
  useCalibrationState,
} from './CalibrationState';
export type {
  CalibratedLightPath,
  CalibratedLightPathOutput,
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
export { IOStateSchema, IOStateDefinition, useIOState } from './IOState';
export type { IOState } from './IOState';
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
export { UC2StateSchema, UC2StateDefinition, useUC2State } from './UC2State';
export type { UC2State } from './UC2State';

export const globalStateDefinition = {
  AutofocusState: AutofocusStateDefinition,
  CalibrationState: CalibrationStateDefinition,
  DetectorState: DetectorStateDefinition,
  ExpanseState: ExpanseStateDefinition,
  HookState: HookStateDefinition,
  IOState: IOStateDefinition,
  MoveState: MoveStateDefinition,
  OpticsState: OpticsStateDefinition,
  SourceState: SourceStateDefinition,
  SwapState: SwapStateDefinition,
  TuneState: TuneStateDefinition,
  UC2State: UC2StateDefinition,
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
