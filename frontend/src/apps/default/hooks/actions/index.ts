import type { ActionDefinition } from '@/lib/arkitekt/task';
import { AcquireDefinition } from './acquire';
import { AcquireMdaDefinition } from './acquireMda';
import { ActivateDetectorDefinition } from './activateDetector';
import { CalibrateLightPathDefinition } from './calibrateLightPath';
import { CalibrateMountDefinition } from './calibrateMount';
import { CaptureImageDefinition } from './captureImage';
import { ClearExpanseDefinition } from './clearExpanse';
import { DeactivateDetectorDefinition } from './deactivateDetector';
import { GalvoGetStatusDefinition } from './galvoGetStatus';
import { GalvoRasterScanDefinition } from './galvoRasterScan';
import { GalvoSetPositionDefinition } from './galvoSetPosition';
import { GalvoStopDefinition } from './galvoStop';
import { HomeObjectiveDefinition } from './homeObjective';
import { HomeStageDefinition } from './homeStage';
import { MountHolderDefinition } from './mountHolder';
import { MoveDefinition } from './move';
import { MoveHomeDefinition } from './moveHome';
import { MoveOneDefinition } from './moveOne';
import { MoveToDefinition } from './moveTo';
import { RegisterMountDefinition } from './registerMount';
import { RunAutofocusDefinition } from './runAutofocus';
import { ScanRegionDefinition } from './scanRegion';
import { SetSampleOriginHereDefinition } from './setSampleOriginHere';
import { SetWindowDefinition } from './setWindow';
import { StartLiveViewDefinition } from './startLiveView';
import { StopLiveViewDefinition } from './stopLiveView';
import { StopStageDefinition } from './stopStage';
import { SwapDefinition } from './swap';
import { TuneDefinition } from './tune';
import { Uc2ScanNodesDefinition } from './uc2ScanNodes';
import { UpdateFirmwareDefinition } from './updateFirmware';

export { createIndexedUnion } from './utils';
export {
  AcquisitionChannelSchema,
  AcquisitionPositionSchema,
  AcquisitionStackSchema,
  SoftwareAutofocusHookSchema,
  ZCalibrationHookSchema,
  MHookUnionSchema,
  THookUnionSchema,
  PHookUnionSchema,
  ZHookUnionSchema,
  AcquisitionPlanSchema,
  AcquireArgsSchema,
  AcquireReturnSchema,
  AcquireDefinition,
  useAcquire,
} from './acquire';
export type {
  AcquisitionChannel,
  AcquisitionChannelOutput,
  AcquisitionPosition,
  AcquisitionPositionOutput,
  AcquisitionStack,
  AcquisitionStackOutput,
  SoftwareAutofocusHook,
  SoftwareAutofocusHookOutput,
  ZCalibrationHook,
  ZCalibrationHookOutput,
  AcquisitionPlan,
  AcquisitionPlanOutput,
  AcquireArgs,
  AcquireReturn,
} from './acquire';
export {
  AcquireMdaArgsSchema,
  AcquireMdaReturnSchema,
  AcquireMdaDefinition,
  useAcquireMda,
} from './acquireMda';
export type { AcquireMdaArgs, AcquireMdaReturn } from './acquireMda';
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
  MeasuredMountSchema,
  CalibrateMountArgsSchema,
  CalibrateMountReturnSchema,
  CalibrateMountDefinition,
  useCalibrateMount,
} from './calibrateMount';
export type {
  MeasuredMount,
  MeasuredMountOutput,
  CalibrateMountArgs,
  CalibrateMountReturn,
} from './calibrateMount';
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
  MountHolderArgsSchema,
  MountHolderReturnSchema,
  MountHolderDefinition,
  useMountHolder,
} from './mountHolder';
export type { MountHolderArgs, MountHolderReturn } from './mountHolder';
export {
  MoveArgsSchema,
  MoveReturnSchema,
  MoveDefinition,
  useMove,
} from './move';
export type { MoveArgs, MoveReturn } from './move';
export {
  MoveHomeArgsSchema,
  MoveHomeReturnSchema,
  MoveHomeDefinition,
  useMoveHome,
} from './moveHome';
export type { MoveHomeArgs, MoveHomeReturn } from './moveHome';
export {
  MoveOneArgsSchema,
  MoveOneReturnSchema,
  MoveOneDefinition,
  useMoveOne,
} from './moveOne';
export type { MoveOneArgs, MoveOneReturn } from './moveOne';
export {
  MoveToArgsSchema,
  MoveToReturnSchema,
  MoveToDefinition,
  useMoveTo,
} from './moveTo';
export type { MoveToArgs, MoveToReturn } from './moveTo';
export {
  RegisterMountArgsSchema,
  RegisterMountReturnSchema,
  RegisterMountDefinition,
  useRegisterMount,
} from './registerMount';
export type { RegisterMountArgs, RegisterMountReturn } from './registerMount';
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
  SetSampleOriginHereArgsSchema,
  SetSampleOriginHereReturnSchema,
  SetSampleOriginHereDefinition,
  useSetSampleOriginHere,
} from './setSampleOriginHere';
export type {
  SetSampleOriginHereArgs,
  SetSampleOriginHereReturn,
} from './setSampleOriginHere';
export {
  AxisWindowSchema,
  SetWindowArgsSchema,
  SetWindowReturnSchema,
  SetWindowDefinition,
  useSetWindow,
} from './setWindow';
export type {
  AxisWindow,
  AxisWindowOutput,
  SetWindowArgs,
  SetWindowReturn,
} from './setWindow';
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
  SwapArgsSchema,
  SwapReturnSchema,
  SwapDefinition,
  useSwap,
} from './swap';
export type { SwapArgs, SwapReturn } from './swap';
export {
  TuneArgsSchema,
  TuneReturnSchema,
  TuneDefinition,
  useTune,
} from './tune';
export type { TuneArgs, TuneReturn } from './tune';
export {
  Uc2ScanNodesArgsSchema,
  Uc2ScanNodesReturnSchema,
  Uc2ScanNodesDefinition,
  useUc2ScanNodes,
} from './uc2ScanNodes';
export type { Uc2ScanNodesArgs, Uc2ScanNodesReturn } from './uc2ScanNodes';
export {
  UpdateFirmwareArgsSchema,
  UpdateFirmwareReturnSchema,
  UpdateFirmwareDefinition,
  useUpdateFirmware,
} from './updateFirmware';
export type {
  UpdateFirmwareArgs,
  UpdateFirmwareReturn,
} from './updateFirmware';

export const globalActionDefinition = {
  Acquire: AcquireDefinition,
  AcquireMda: AcquireMdaDefinition,
  ActivateDetector: ActivateDetectorDefinition,
  CalibrateLightPath: CalibrateLightPathDefinition,
  CalibrateMount: CalibrateMountDefinition,
  CaptureImage: CaptureImageDefinition,
  ClearExpanse: ClearExpanseDefinition,
  DeactivateDetector: DeactivateDetectorDefinition,
  GalvoGetStatus: GalvoGetStatusDefinition,
  GalvoRasterScan: GalvoRasterScanDefinition,
  GalvoSetPosition: GalvoSetPositionDefinition,
  GalvoStop: GalvoStopDefinition,
  HomeObjective: HomeObjectiveDefinition,
  HomeStage: HomeStageDefinition,
  MountHolder: MountHolderDefinition,
  Move: MoveDefinition,
  MoveHome: MoveHomeDefinition,
  MoveOne: MoveOneDefinition,
  MoveTo: MoveToDefinition,
  RegisterMount: RegisterMountDefinition,
  RunAutofocus: RunAutofocusDefinition,
  ScanRegion: ScanRegionDefinition,
  SetSampleOriginHere: SetSampleOriginHereDefinition,
  SetWindow: SetWindowDefinition,
  StartLiveView: StartLiveViewDefinition,
  StopLiveView: StopLiveViewDefinition,
  StopStage: StopStageDefinition,
  Swap: SwapDefinition,
  Tune: TuneDefinition,
  Uc2ScanNodes: Uc2ScanNodesDefinition,
  UpdateFirmware: UpdateFirmwareDefinition,
} satisfies Record<string, ActionDefinition<unknown, unknown>>;

export type GlobalActionDefinition = typeof globalActionDefinition;
export const globalActionDefintiion = globalActionDefinition;
