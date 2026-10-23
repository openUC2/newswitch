import type { ActionDefinition } from '@/lib/arkitekt/task';
import { AcquireMultidimensionalAcquisitionDefinition } from './acquireMultidimensionalAcquisition';
import { ActivateDetectorDefinition } from './activateDetector';
import { CalibrateLightPathDefinition } from './calibrateLightPath';
import { CaptureImageDefinition } from './captureImage';
import { ClearExpanseDefinition } from './clearExpanse';
import { DeactivateDetectorDefinition } from './deactivateDetector';
import { GalvoGetStatusDefinition } from './galvoGetStatus';
import { GalvoRasterScanDefinition } from './galvoRasterScan';
import { GalvoSetPositionDefinition } from './galvoSetPosition';
import { GalvoStopDefinition } from './galvoStop';
import { HomeObjectiveDefinition } from './homeObjective';
import { HomeStageDefinition } from './homeStage';
import { LedMatrixFillDefinition } from './ledMatrixFill';
import { LedMatrixOffDefinition } from './ledMatrixOff';
import { MoveHomeDefinition } from './moveHome';
import { MoveStageDefinition } from './moveStage';
import { RunAutofocusDefinition } from './runAutofocus';
import { ScanRegionDefinition } from './scanRegion';
import { SetIlluminationIntensityDefinition } from './setIlluminationIntensity';
import { StartLiveViewDefinition } from './startLiveView';
import { StopLiveViewDefinition } from './stopLiveView';
import { StopStageDefinition } from './stopStage';
import { SwitchFilterDefinition } from './switchFilter';
import { SwitchObjectiveDefinition } from './switchObjective';
import { ToggleFilterDefinition } from './toggleFilter';
import { ToggleObjectiveDefinition } from './toggleObjective';
import { TurnOffIlluminationChannelDefinition } from './turnOffIlluminationChannel';
import { TurnOnIlluminationDefinition } from './turnOnIllumination';
import { Uc2ScanNodesDefinition } from './uc2ScanNodes';
import { UpdateDetectorDefinition } from './updateDetector';

export { createIndexedUnion } from './utils';
export {
  StreamIlluminationSchema,
  StreamsSchema,
  SoftwareAutofocusHookSchema,
  ZCalibrationHookSchema,
  ZHookUnionSchema,
  StackSchema,
  PHookUnionSchema,
  PositionSchema,
  THookUnionSchema,
  TimepointSchema,
  MHookUnionSchema,
  MultidimensionalAcquisitionSchema,
  AcquireMultidimensionalAcquisitionArgsSchema,
  AcquireMultidimensionalAcquisitionReturnSchema,
  AcquireMultidimensionalAcquisitionDefinition,
  useAcquireMultidimensionalAcquisition,
} from './acquireMultidimensionalAcquisition';
export type {
  StreamIllumination,
  StreamIlluminationOutput,
  Streams,
  StreamsOutput,
  SoftwareAutofocusHook,
  SoftwareAutofocusHookOutput,
  ZCalibrationHook,
  ZCalibrationHookOutput,
  Stack,
  StackOutput,
  Position,
  PositionOutput,
  Timepoint,
  TimepointOutput,
  MultidimensionalAcquisition,
  MultidimensionalAcquisitionOutput,
  AcquireMultidimensionalAcquisitionArgs,
  AcquireMultidimensionalAcquisitionReturn,
} from './acquireMultidimensionalAcquisition';
export {
  ActivateDetectorArgsSchema,
  ActivateDetectorReturnSchema,
  ActivateDetectorDefinition,
  useActivateDetector,
} from './activateDetector';
export type {
  ActivateDetectorArgs,
  ActivateDetectorReturn,
} from './activateDetector';
export {
  CalibratedLightPathSchema,
  CalibrateLightPathArgsSchema,
  CalibrateLightPathReturnSchema,
  CalibrateLightPathDefinition,
  useCalibrateLightPath,
} from './calibrateLightPath';
export type {
  CalibratedLightPath,
  CalibratedLightPathOutput,
  CalibrateLightPathArgs,
  CalibrateLightPathReturn,
} from './calibrateLightPath';
export {
  CaptureImageArgsSchema,
  CaptureImageReturnSchema,
  CaptureImageDefinition,
  useCaptureImage,
} from './captureImage';
export type { CaptureImageArgs, CaptureImageReturn } from './captureImage';
export {
  ClearExpanseArgsSchema,
  ClearExpanseReturnSchema,
  ClearExpanseDefinition,
  useClearExpanse,
} from './clearExpanse';
export type { ClearExpanseArgs, ClearExpanseReturn } from './clearExpanse';
export {
  DeactivateDetectorArgsSchema,
  DeactivateDetectorReturnSchema,
  DeactivateDetectorDefinition,
  useDeactivateDetector,
} from './deactivateDetector';
export type {
  DeactivateDetectorArgs,
  DeactivateDetectorReturn,
} from './deactivateDetector';
export {
  GalvoStatusSchema,
  GalvoGetStatusArgsSchema,
  GalvoGetStatusReturnSchema,
  GalvoGetStatusDefinition,
  useGalvoGetStatus,
} from './galvoGetStatus';
export type {
  GalvoStatus,
  GalvoStatusOutput,
  GalvoGetStatusArgs,
  GalvoGetStatusReturn,
} from './galvoGetStatus';
export {
  GalvoRasterScanArgsSchema,
  GalvoRasterScanReturnSchema,
  GalvoRasterScanDefinition,
  useGalvoRasterScan,
} from './galvoRasterScan';
export type {
  GalvoRasterScanArgs,
  GalvoRasterScanReturn,
} from './galvoRasterScan';
export {
  GalvoSetPositionArgsSchema,
  GalvoSetPositionReturnSchema,
  GalvoSetPositionDefinition,
  useGalvoSetPosition,
} from './galvoSetPosition';
export type {
  GalvoSetPositionArgs,
  GalvoSetPositionReturn,
} from './galvoSetPosition';
export {
  GalvoStopArgsSchema,
  GalvoStopReturnSchema,
  GalvoStopDefinition,
  useGalvoStop,
} from './galvoStop';
export type { GalvoStopArgs, GalvoStopReturn } from './galvoStop';
export {
  HomeObjectiveArgsSchema,
  HomeObjectiveReturnSchema,
  HomeObjectiveDefinition,
  useHomeObjective,
} from './homeObjective';
export type { HomeObjectiveArgs, HomeObjectiveReturn } from './homeObjective';
export {
  HomeStageArgsSchema,
  HomeStageReturnSchema,
  HomeStageDefinition,
  useHomeStage,
} from './homeStage';
export type { HomeStageArgs, HomeStageReturn } from './homeStage';
export {
  LedMatrixFillArgsSchema,
  LedMatrixFillReturnSchema,
  LedMatrixFillDefinition,
  useLedMatrixFill,
} from './ledMatrixFill';
export type { LedMatrixFillArgs, LedMatrixFillReturn } from './ledMatrixFill';
export {
  LedMatrixOffArgsSchema,
  LedMatrixOffReturnSchema,
  LedMatrixOffDefinition,
  useLedMatrixOff,
} from './ledMatrixOff';
export type { LedMatrixOffArgs, LedMatrixOffReturn } from './ledMatrixOff';
export {
  MoveHomeArgsSchema,
  MoveHomeReturnSchema,
  MoveHomeDefinition,
  useMoveHome,
} from './moveHome';
export type { MoveHomeArgs, MoveHomeReturn } from './moveHome';
export {
  MoveStageArgsSchema,
  MoveStageReturnSchema,
  MoveStageDefinition,
  useMoveStage,
  OptimisticStageState,
} from './moveStage';
export type { MoveStageArgs, MoveStageReturn } from './moveStage';
export {
  RunAutofocusArgsSchema,
  RunAutofocusReturnSchema,
  RunAutofocusDefinition,
  useRunAutofocus,
} from './runAutofocus';
export type { RunAutofocusArgs, RunAutofocusReturn } from './runAutofocus';
export {
  ScanRegionArgsSchema,
  ScanRegionReturnSchema,
  ScanRegionDefinition,
  useScanRegion,
} from './scanRegion';
export type { ScanRegionArgs, ScanRegionReturn } from './scanRegion';
export {
  SetIlluminationIntensityArgsSchema,
  SetIlluminationIntensityReturnSchema,
  SetIlluminationIntensityDefinition,
  useSetIlluminationIntensity,
} from './setIlluminationIntensity';
export type {
  SetIlluminationIntensityArgs,
  SetIlluminationIntensityReturn,
} from './setIlluminationIntensity';
export {
  StartLiveViewArgsSchema,
  StartLiveViewReturnSchema,
  StartLiveViewDefinition,
  useStartLiveView,
} from './startLiveView';
export type { StartLiveViewArgs, StartLiveViewReturn } from './startLiveView';
export {
  StopLiveViewArgsSchema,
  StopLiveViewReturnSchema,
  StopLiveViewDefinition,
  useStopLiveView,
} from './stopLiveView';
export type { StopLiveViewArgs, StopLiveViewReturn } from './stopLiveView';
export {
  StopStageArgsSchema,
  StopStageReturnSchema,
  StopStageDefinition,
  useStopStage,
} from './stopStage';
export type { StopStageArgs, StopStageReturn } from './stopStage';
export {
  SwitchFilterArgsSchema,
  SwitchFilterReturnSchema,
  SwitchFilterDefinition,
  useSwitchFilter,
} from './switchFilter';
export type { SwitchFilterArgs, SwitchFilterReturn } from './switchFilter';
export {
  SwitchObjectiveArgsSchema,
  SwitchObjectiveReturnSchema,
  SwitchObjectiveDefinition,
  useSwitchObjective,
} from './switchObjective';
export type {
  SwitchObjectiveArgs,
  SwitchObjectiveReturn,
} from './switchObjective';
export {
  ToggleFilterArgsSchema,
  ToggleFilterReturnSchema,
  ToggleFilterDefinition,
  useToggleFilter,
} from './toggleFilter';
export type { ToggleFilterArgs, ToggleFilterReturn } from './toggleFilter';
export {
  ToggleObjectiveArgsSchema,
  ToggleObjectiveReturnSchema,
  ToggleObjectiveDefinition,
  useToggleObjective,
} from './toggleObjective';
export type {
  ToggleObjectiveArgs,
  ToggleObjectiveReturn,
} from './toggleObjective';
export {
  TurnOffIlluminationChannelArgsSchema,
  TurnOffIlluminationChannelReturnSchema,
  TurnOffIlluminationChannelDefinition,
  useTurnOffIlluminationChannel,
} from './turnOffIlluminationChannel';
export type {
  TurnOffIlluminationChannelArgs,
  TurnOffIlluminationChannelReturn,
} from './turnOffIlluminationChannel';
export {
  TurnOnIlluminationArgsSchema,
  TurnOnIlluminationReturnSchema,
  TurnOnIlluminationDefinition,
  useTurnOnIllumination,
} from './turnOnIllumination';
export type {
  TurnOnIlluminationArgs,
  TurnOnIlluminationReturn,
} from './turnOnIllumination';
export {
  Uc2ScanNodesArgsSchema,
  Uc2ScanNodesReturnSchema,
  Uc2ScanNodesDefinition,
  useUc2ScanNodes,
} from './uc2ScanNodes';
export type { Uc2ScanNodesArgs, Uc2ScanNodesReturn } from './uc2ScanNodes';
export {
  DetectorSchema,
  UpdateDetectorArgsSchema,
  UpdateDetectorReturnSchema,
  UpdateDetectorDefinition,
  useUpdateDetector,
} from './updateDetector';
export type {
  Detector,
  DetectorOutput,
  UpdateDetectorArgs,
  UpdateDetectorReturn,
} from './updateDetector';

export const globalActionDefinition = {
  AcquireMultidimensionalAcquisition:
    AcquireMultidimensionalAcquisitionDefinition,
  ActivateDetector: ActivateDetectorDefinition,
  CalibrateLightPath: CalibrateLightPathDefinition,
  CaptureImage: CaptureImageDefinition,
  ClearExpanse: ClearExpanseDefinition,
  DeactivateDetector: DeactivateDetectorDefinition,
  GalvoGetStatus: GalvoGetStatusDefinition,
  GalvoRasterScan: GalvoRasterScanDefinition,
  GalvoSetPosition: GalvoSetPositionDefinition,
  GalvoStop: GalvoStopDefinition,
  HomeObjective: HomeObjectiveDefinition,
  HomeStage: HomeStageDefinition,
  LedMatrixFill: LedMatrixFillDefinition,
  LedMatrixOff: LedMatrixOffDefinition,
  MoveHome: MoveHomeDefinition,
  MoveStage: MoveStageDefinition,
  RunAutofocus: RunAutofocusDefinition,
  ScanRegion: ScanRegionDefinition,
  SetIlluminationIntensity: SetIlluminationIntensityDefinition,
  StartLiveView: StartLiveViewDefinition,
  StopLiveView: StopLiveViewDefinition,
  StopStage: StopStageDefinition,
  SwitchFilter: SwitchFilterDefinition,
  SwitchObjective: SwitchObjectiveDefinition,
  ToggleFilter: ToggleFilterDefinition,
  ToggleObjective: ToggleObjectiveDefinition,
  TurnOffIlluminationChannel: TurnOffIlluminationChannelDefinition,
  TurnOnIllumination: TurnOnIlluminationDefinition,
  Uc2ScanNodes: Uc2ScanNodesDefinition,
  UpdateDetector: UpdateDetectorDefinition,
} satisfies Record<string, ActionDefinition<unknown, unknown>>;

export type GlobalActionDefinition = typeof globalActionDefinition;
export const globalActionDefintiion = globalActionDefinition;
