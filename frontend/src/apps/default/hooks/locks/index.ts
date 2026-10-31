import type { LockDefinition } from '@/lib/arkitekt/locks';
import { DetectorDefinition } from './Detector';
import { ExpanseStateDefinition } from './ExpanseState';
import { GalvoDefinition } from './Galvo';
import { IoDefinition } from './Io';
import { MotionDefinition } from './Motion';
import { SwapDefinition } from './Swap';
import { TuneDefinition } from './Tune';

export { DetectorDefinition, useDetectorLock } from './Detector';
export { ExpanseStateDefinition, useExpanseStateLock } from './ExpanseState';
export { GalvoDefinition, useGalvoLock } from './Galvo';
export { IoDefinition, useIoLock } from './Io';
export { MotionDefinition, useMotionLock } from './Motion';
export { SwapDefinition, useSwapLock } from './Swap';
export { TuneDefinition, useTuneLock } from './Tune';

export const globalLockDefinition = {
  Detector: DetectorDefinition,
  ExpanseState: ExpanseStateDefinition,
  Galvo: GalvoDefinition,
  Io: IoDefinition,
  Motion: MotionDefinition,
  Swap: SwapDefinition,
  Tune: TuneDefinition,
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
