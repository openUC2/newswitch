import type { ActionDefinition } from '@/lib/arkitekt/task';
import { AcquireDefinition } from './acquire';
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
import { MoveDefinition } from './move';
import { MoveHomeDefinition } from './moveHome';
import { MoveOneDefinition } from './moveOne';
import { RunAutofocusDefinition } from './runAutofocus';
import { ScanRegionDefinition } from './scanRegion';
import { SetRegionDefinition } from './setRegion';
import { StartLiveViewDefinition } from './startLiveView';
import { StopLiveViewDefinition } from './stopLiveView';
import { StopStageDefinition } from './stopStage';
import { SwapDefinition } from './swap';
import { TuneDefinition } from './tune';
import { Uc2ScanNodesDefinition } from './uc2ScanNodes';

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
  AcquiredDatasetSchema,
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
  AcquiredDataset,
  AcquiredDatasetOutput,
  AcquireArgs,
  AcquireReturn,
} from './acquire';
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
  SetRegionArgsSchema,
  SetRegionReturnSchema,
  SetRegionDefinition,
  useSetRegion,
} from './setRegion';
export type { SetRegionArgs, SetRegionReturn } from './setRegion';
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

export const globalActionDefinition = {
  Acquire: AcquireDefinition,
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
  Move: MoveDefinition,
  MoveHome: MoveHomeDefinition,
  MoveOne: MoveOneDefinition,
  RunAutofocus: RunAutofocusDefinition,
  ScanRegion: ScanRegionDefinition,
  SetRegion: SetRegionDefinition,
  StartLiveView: StartLiveViewDefinition,
  StopLiveView: StopLiveViewDefinition,
  StopStage: StopStageDefinition,
  Swap: SwapDefinition,
  Tune: TuneDefinition,
  Uc2ScanNodes: Uc2ScanNodesDefinition,
} satisfies Record<string, ActionDefinition<unknown, unknown>>;

export type GlobalActionDefinition = typeof globalActionDefinition;
export const globalActionDefintiion = globalActionDefinition;
