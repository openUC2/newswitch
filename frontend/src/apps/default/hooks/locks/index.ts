import type { LockDefinition } from '@/lib/rekuest/locks';
import { CameraParametersDefinition } from './CameraParameters';
import { ExpanseStateDefinition } from './ExpanseState';
import { FilterBankDefinition } from './FilterBank';
import { GalvoDefinition } from './Galvo';
import { HookRegistryDefinition } from './HookRegistry';
import { IlluminationDefinition } from './Illumination';
import { IoDefinition } from './Io';
import { ObjectiveDefinition } from './Objective';
import { StagePositionDefinition } from './StagePosition';

export {
  CameraParametersDefinition,
  useCameraParametersLock,
} from './CameraParameters';
export { ExpanseStateDefinition, useExpanseStateLock } from './ExpanseState';
export { FilterBankDefinition, useFilterBankLock } from './FilterBank';
export { GalvoDefinition, useGalvoLock } from './Galvo';
export { HookRegistryDefinition, useHookRegistryLock } from './HookRegistry';
export { IlluminationDefinition, useIlluminationLock } from './Illumination';
export { IoDefinition, useIoLock } from './Io';
export { ObjectiveDefinition, useObjectiveLock } from './Objective';
export { StagePositionDefinition, useStagePositionLock } from './StagePosition';

export const globalLockDefinition = {
  CameraParameters: CameraParametersDefinition,
  ExpanseState: ExpanseStateDefinition,
  FilterBank: FilterBankDefinition,
  Galvo: GalvoDefinition,
  HookRegistry: HookRegistryDefinition,
  Illumination: IlluminationDefinition,
  Io: IoDefinition,
  Objective: ObjectiveDefinition,
  StagePosition: StagePositionDefinition,
} satisfies Record<string, LockDefinition<string>>;

export type GlobalLockDefinition = typeof globalLockDefinition;
type InferLockKey<TDefinition> =
  TDefinition extends LockDefinition<infer TKey> ? TKey : never;

export type GlobalLockKey = InferLockKey<
  GlobalLockDefinition[keyof GlobalLockDefinition]
>;
export const globalLockKeys = Object.values(globalLockDefinition).map(
  (definition) => definition.key,
) as GlobalLockKey[];
export const globalLockDefintiion = globalLockDefinition;
