import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { z } from "zod";
import { createGlobalStateStore } from "./store";
import { createIndexedUnion } from "@/apps/default/hooks/states/utils";
import {
  StateEventType,
  type StatePatchEvent,
} from "@/lib/arkitekt/transport/types";

/**
 * The replay/live state model: the backend streams JSON-patch events, the store applies
 * them to the current snapshot and tracks the global revision. Getting this wrong means
 * silently showing the wrong microscope state, so it is worth pinning down.
 */

const makePatch = (
  overrides: Partial<StatePatchEvent> = {},
): StatePatchEvent => ({
  type: StateEventType.STATE_PATCH,
  session_id: "session-1",
  global_rev: 1,
  state_name: "StageState",
  ts: 1_000,
  op: "replace",
  path: "/x",
  value: 42,
  task_id: "task-1",
  ...overrides,
});

describe("globalStateStore.applyPatch", () => {
  beforeEach(() => {
    // The store logs on every patch; keep the test output readable.
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("applies a replace patch and advances the global revision", () => {
    const store = createGlobalStateStore();
    store.getState().setState("StageState", { x: 0, y: 5 });

    store
      .getState()
      .applyPatch(
        makePatch({ op: "replace", path: "/x", value: 42, global_rev: 7 }),
      );

    expect(store.getState().states.StageState).toEqual({ x: 42, y: 5 });
    expect(store.getState().globalRevision).toBe(7);
  });

  it("applies an add patch without disturbing sibling keys", () => {
    const store = createGlobalStateStore();
    store.getState().setState("StageState", { x: 1 });

    store.getState().applyPatch(makePatch({ op: "add", path: "/z", value: 3 }));

    expect(store.getState().states.StageState).toEqual({ x: 1, z: 3 });
  });

  it("leaves the previous state intact when a patch cannot be applied", () => {
    const store = createGlobalStateStore();
    store.getState().setState("StageState", { x: 1 });

    // /missing/deep does not exist, so fast-json-patch throws; the store must swallow it
    // rather than leave a half-applied document behind.
    store.getState().applyPatch(
      makePatch({
        op: "replace",
        path: "/missing/deep",
        value: 9,
        global_rev: 99,
      }),
    );

    expect(store.getState().states.StageState).toEqual({ x: 1 });
    expect(store.getState().globalRevision).not.toBe(99);
  });

  it("does not mutate the previous state object in place", () => {
    const store = createGlobalStateStore();
    const original = { x: 0 };
    store.getState().setState("StageState", original);

    store
      .getState()
      .applyPatch(makePatch({ op: "replace", path: "/x", value: 5 }));

    // The store clones before patching; the caller's object must not be rewritten.
    expect(original.x).toBe(0);
  });

  it("caps the latestPatches ring buffer at the configured size", () => {
    const store = createGlobalStateStore({ latestPatchesBufferSize: 3 });
    store.getState().setState("StageState", { x: 0 });

    for (let i = 1; i <= 5; i += 1) {
      store
        .getState()
        .applyPatch(makePatch({ value: i, global_rev: i, ts: i }));
    }

    const { latestPatches } = store.getState();
    expect(latestPatches).toHaveLength(3);
    // Oldest entries are dropped, newest kept.
    expect(latestPatches.map((entry) => entry.ts)).toEqual([3, 4, 5]);
  });

  it("drops patches for a state that never hydrated", () => {
    const store = createGlobalStateStore();

    // A failed checkout leaves the state absent. Patching it must not record the patch or
    // advance the revision - and must not JSON.parse(undefined) on the way.
    store.getState().applyPatch(makePatch({ global_rev: 12 }));

    expect(store.getState().states.StageState).toBeUndefined();
    expect(store.getState().latestPatches).toHaveLength(0);
    expect(store.getState().globalRevision).not.toBe(12);
    expect(console.error).toHaveBeenCalledWith(
      expect.stringContaining("not hydrated"),
    );
  });

  it("decodes a patched document through the state schema", () => {
    const store = createGlobalStateStore();
    const schema = z.object({
      x: z.number(),
      kube: createIndexedUnion([
        z.object({ kube_id: z.string() }),
        z.object({ wavelength: z.number() }),
      ]),
    });

    store.getState().setState("StageState", { x: 0, kube: { kube_id: "a" } });

    // A patch value arrives in wire form; the schema is what turns it back into a flat kube.
    store.getState().applyPatch(
      makePatch({
        op: "replace",
        path: "/kube",
        value: { __use: 1, __value: { wavelength: 525 } },
      }),
      schema,
    );

    expect(store.getState().states.StageState).toEqual({
      x: 0,
      kube: { wavelength: 525 },
    });
  });

  it("keeps the previous value when a patched document fails validation", () => {
    const store = createGlobalStateStore();
    const schema = z.object({ x: z.number() });

    store.getState().setState("StageState", { x: 1 });

    store
      .getState()
      .applyPatch(
        makePatch({ op: "replace", path: "/x", value: "not-a-number" }),
        schema,
      );

    expect(store.getState().states.StageState).toEqual({ x: 1 });
  });
});
