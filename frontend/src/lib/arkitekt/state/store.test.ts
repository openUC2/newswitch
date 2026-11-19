import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { z } from "zod";
import { createGlobalStateStore } from "./store";
import { createIndexedUnion } from "@/apps/default/hooks/states/utils";
import {
  StateEventType,
  type StateOp,
  type StateUpdateEvent,
} from "@/lib/arkitekt/transport/types";

/**
 * The replay/live state model: the backend streams state updates (each a list of JSON-patch
 * operations), the store applies them to the current snapshot and tracks the global revision. Getting this wrong means
 * silently showing the wrong microscope state, so it is worth pinning down.
 */

const REPLACE_X: StateOp = { op: "replace", path: "/x", value: 42 };

/** An update of StageState made of `op` alone, unless `overrides` gives its `ops`. */
const makeUpdate = (
  op: Partial<StateOp> = {},
  overrides: Partial<StateUpdateEvent> = {},
): StateUpdateEvent => ({
  type: StateEventType.STATE_UPDATE,
  state: "StageState",
  global_rev: 1,
  ops: [{ ...REPLACE_X, ...op }],
  task: "task-1",
  ...overrides,
});

describe("globalStateStore.applyUpdate", () => {
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
      .applyUpdate(
        makeUpdate({ op: "replace", path: "/x", value: 42 }, { global_rev: 7 }),
      );

    expect(store.getState().states.StageState).toEqual({ x: 42, y: 5 });
    expect(store.getState().globalRevision).toBe(7);
  });

  it("applies an add patch without disturbing sibling keys", () => {
    const store = createGlobalStateStore();
    store.getState().setState("StageState", { x: 1 });

    store
      .getState()
      .applyUpdate(makeUpdate({ op: "add", path: "/z", value: 3 }));

    expect(store.getState().states.StageState).toEqual({ x: 1, z: 3 });
  });

  it("leaves the previous state intact when a patch cannot be applied", () => {
    const store = createGlobalStateStore();
    store.getState().setState("StageState", { x: 1 });

    // /missing/deep does not exist, so fast-json-patch throws; the store must swallow it
    // rather than leave a half-applied document behind.
    store
      .getState()
      .applyUpdate(
        makeUpdate(
          { op: "replace", path: "/missing/deep", value: 9 },
          { global_rev: 99 },
        ),
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
      .applyUpdate(makeUpdate({ op: "replace", path: "/x", value: 5 }));

    // The store clones before patching; the caller's object must not be rewritten.
    expect(original.x).toBe(0);
  });

  it("caps the latestPatches ring buffer at the configured size", () => {
    const store = createGlobalStateStore({ latestPatchesBufferSize: 3 });
    store.getState().setState("StageState", { x: 0 });

    for (let i = 1; i <= 5; i += 1) {
      store
        .getState()
        .applyUpdate(makeUpdate({ value: i }, { global_rev: i, agent_ts: i }));
    }

    const { latestPatches } = store.getState();
    expect(latestPatches).toHaveLength(3);
    // Oldest entries are dropped, newest kept.
    expect(latestPatches.map((entry) => entry.ts)).toEqual([3000, 4000, 5000]);
  });

  it("drops patches for a state that never hydrated", () => {
    const store = createGlobalStateStore();

    // A failed checkout leaves the state absent. Patching it must not record the patch or
    // advance the revision - and must not JSON.parse(undefined) on the way.
    store.getState().applyUpdate(makeUpdate({}, { global_rev: 12 }));

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
    store.getState().applyUpdate(
      makeUpdate({
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
      .applyUpdate(
        makeUpdate({ op: "replace", path: "/x", value: "not-a-number" }),
        schema,
      );

    expect(store.getState().states.StageState).toEqual({ x: 1 });
  });

  it("applies every operation of an update together", () => {
    const store = createGlobalStateStore();
    store.getState().setState("StageState", { x: 0, y: 0 });

    store.getState().applyUpdate(
      makeUpdate(
        {},
        {
          global_rev: 3,
          ops: [
            { op: "replace", path: "/x", value: 1 },
            { op: "replace", path: "/y", value: 2 },
          ],
        },
      ),
    );

    expect(store.getState().states.StageState).toEqual({ x: 1, y: 2 });
    expect(store.getState().globalRevision).toBe(3);
    expect(store.getState().latestPatches.map((entry) => entry.path)).toEqual([
      "/x",
      "/y",
    ]);
  });

  it("applies none of an update when one of its operations fails", () => {
    const store = createGlobalStateStore();
    store.getState().setState("StageState", { x: 0 });

    store.getState().applyUpdate(
      makeUpdate(
        {},
        {
          global_rev: 4,
          ops: [
            { op: "replace", path: "/x", value: 1 },
            { op: "replace", path: "/missing/deep", value: 9 },
          ],
        },
      ),
    );

    expect(store.getState().states.StageState).toEqual({ x: 0 });
    expect(store.getState().globalRevision).not.toBe(4);
  });
});
