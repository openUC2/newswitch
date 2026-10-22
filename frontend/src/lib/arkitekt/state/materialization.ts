import { applyPatch, type Operation } from "fast-json-patch";
import type { SnapshotEnvelope } from "@/lib/arkitekt/state/store";
import type {
  RetrieverPatchEventResponse,
  RevisedStatesSnapshotMap,
  StateSegmentsResponse,
} from "@/lib/arkitekt/transport/types";

export const DEFAULT_MAX_LOCAL_MATERIALIZATION_EVENTS = 250;
export const DEFAULT_FORWARD_EVENT_WINDOW = 50;

export type CheckoutConfig = {
  maxLocalMaterializationEvents: number;
  forwardEventWindow: number;
};

export type LocalMaterializationPlan = {
  baseSnapshot: SnapshotEnvelope;
  segments: StateSegmentsResponse[];
  eventCount: number;
};

const deepClone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

/**
 * The transport API accepts revision identifiers as `string | number`, but the
 * local history cache can only replay forward ranges when the identifier is a
 * numeric global revision.
 */
export function toNumericGlobalRevision(
  revision: string | number,
): number | null {
  const numericRevision =
    typeof revision === "number" ? revision : Number(revision);
  return Number.isFinite(numericRevision) ? numericRevision : null;
}

export function toSnapshotMap(
  snapshot: SnapshotEnvelope,
): RevisedStatesSnapshotMap {
  return Object.fromEntries(
    snapshot.state_snapshots.map((stateSnapshot) => [
      stateSnapshot.name,
      {
        value: deepClone(stateSnapshot.value),
        revision: stateSnapshot.revision,
      },
    ]),
  );
}

function hasAllStateKeys(snapshot: SnapshotEnvelope, stateKeys: string[]) {
  const availableKeys = new Set(
    snapshot.state_snapshots.map((entry) => entry.name),
  );
  return stateKeys.every((stateKey) => availableKeys.has(stateKey));
}

function countSegmentEvents(segments: StateSegmentsResponse[]) {
  return segments.reduce((count, segment) => count + segment.patches.length, 0);
}

function normalizePatchOperations(patch: unknown): Operation[] {
  if (Array.isArray(patch)) {
    return patch as Operation[];
  }

  if (patch == null) {
    return [];
  }

  return [patch as Operation];
}

function sortPatchEvents(
  left: RetrieverPatchEventResponse,
  right: RetrieverPatchEventResponse,
) {
  if (left.global_current_rev !== right.global_current_rev) {
    return left.global_current_rev - right.global_current_rev;
  }

  if (left.global_future_rev !== right.global_future_rev) {
    return left.global_future_rev - right.global_future_rev;
  }

  return (
    new Date(left.timepoint).getTime() - new Date(right.timepoint).getTime()
  );
}

function resolveMaterializedStateKey(
  materialized: RevisedStatesSnapshotMap,
  stateId: string,
): string | null {
  if (stateId in materialized) {
    return stateId;
  }

  const normalizedStateId = stateId.trim().toLowerCase();
  const matchedEntry = Object.keys(materialized).find(
    (key) => key.trim().toLowerCase() === normalizedStateId,
  );

  return matchedEntry ?? null;
}

/**
 * Cached patch segments are stored as forward-only contiguous ranges. This
 * function finds a replay plan from a cached snapshot to the requested target.
 */
export function buildLocalMaterializationPlan(
  snapshots: SnapshotEnvelope[],
  segments: StateSegmentsResponse[],
  stateKeys: string[],
  targetRevision: number,
  maxLocalMaterializationEvents: number,
): LocalMaterializationPlan | null {
  const candidateSnapshots = snapshots
    .filter((snapshot) => hasAllStateKeys(snapshot, stateKeys))
    .map((snapshot) => ({
      snapshot,
      numericRevision: toNumericGlobalRevision(snapshot.revision),
    }))
    .filter(
      (
        snapshot,
      ): snapshot is { snapshot: SnapshotEnvelope; numericRevision: number } =>
        snapshot.numericRevision !== null &&
        snapshot.numericRevision <= targetRevision,
    )
    .sort((left, right) => right.numericRevision - left.numericRevision);

  const sortedSegments = [...segments].sort(
    (left, right) => left.from_global_revision - right.from_global_revision,
  );

  for (const candidate of candidateSnapshots) {
    let cursor = candidate.numericRevision;
    const collectedSegments: StateSegmentsResponse[] = [];

    while (cursor < targetRevision) {
      const nextSegment = sortedSegments.find(
        (segment) =>
          segment.from_global_revision === cursor &&
          segment.to_global_revision <= targetRevision,
      );

      if (!nextSegment) {
        break;
      }

      collectedSegments.push(nextSegment);
      cursor = nextSegment.to_global_revision;
    }

    if (cursor !== targetRevision) {
      continue;
    }

    const eventCount = countSegmentEvents(collectedSegments);
    if (eventCount > maxLocalMaterializationEvents) {
      return null;
    }

    return {
      baseSnapshot: candidate.snapshot,
      segments: collectedSegments,
      eventCount,
    };
  }

  return null;
}

export function materializeSnapshotMap(
  baseSnapshots: RevisedStatesSnapshotMap,
  segments: StateSegmentsResponse[],
): RevisedStatesSnapshotMap {
  const materialized = deepClone(baseSnapshots);

  for (const segment of segments) {
    for (const patchEvent of [...segment.patches].sort(sortPatchEvents)) {
      const resolvedStateKey = resolveMaterializedStateKey(
        materialized,
        patchEvent.state_id,
      );
      const currentState = resolvedStateKey
        ? materialized[resolvedStateKey]
        : undefined;

      if (!resolvedStateKey || !currentState) {
        throw new Error(
          `Cannot materialize unknown state ${patchEvent.state_id} from cached history. `,
        );
      }

      const patchedValue = applyPatch(
        deepClone(currentState.value),
        normalizePatchOperations(patchEvent.patch),
      ).newDocument;

      materialized[resolvedStateKey] = {
        value: patchedValue,
        revision: patchEvent.global_future_rev,
      };
    }
  }

  return materialized;
}
