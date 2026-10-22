// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { bloks } from "@/apps/default/bloks";
import { SwitchObjectiveArgsSchema } from "@/apps/default/hooks/actions/switchObjective";
import {
  actionArgOrder,
  foreignDependencyKeys,
  mapActionArguments,
  mergeLiveState,
  selfStateKeys,
  taskUpdateOf,
  type NewswitchBlokDeclaration,
} from "./newswitch";
import BlokRenderer from "./renderer/BlokRenderer";
import {
  normalizeBlokComponentTree,
  type BlokDispatchActionHandler,
} from "./renderer/runtime";

const jonda: NewswitchBlokDeclaration = bloks.jonda;

const lens = (slot: number, name: string) => ({
  slot,
  name,
  magnification: 10,
  numerical_aperture: 0.3,
  working_distance: 1,
  binning_factor: 1,
});

afterEach(cleanup);

describe("newswitch blok helpers", () => {
  it("reads the self states a blok depends on", () => {
    expect(selfStateKeys(jonda)).toEqual(["ObjectiveState"]);
    expect(foreignDependencyKeys(jonda)).toEqual([]);
  });

  it("names positional arguments by the blok's demand", () => {
    const order = actionArgOrder(jonda, "switch_objective");
    expect(order).toEqual(["slot"]);
    expect(mapActionArguments({ "0": 2 }, order)).toEqual({
      ok: true,
      args: { slot: 2 },
    });
  });

  it("falls back to the args schema's order without a demand", () => {
    expect(
      actionArgOrder(
        { key: "x", components: [] },
        "switch_objective",
        SwitchObjectiveArgsSchema,
      ),
    ).toEqual(["slot"]);
  });

  it("passes named arguments through and refuses unknown positions", () => {
    expect(mapActionArguments({ slot: 1 }, [])).toEqual({
      ok: true,
      args: { slot: 1 },
    });
    expect(mapActionArguments({ "1": 1 }, ["slot"]).ok).toBe(false);
    expect(mapActionArguments({ "0": 1, slot: 2 }, ["slot"]).ok).toBe(false);
  });

  it("lays live state over the demo state", () => {
    const live = { slot: 1, name: "a", magnification: 4, mounted_lenses: [] };
    expect(mergeLiveState(jonda.demoState, { ObjectiveState: null })).toBe(
      jonda.demoState,
    );
    expect(
      mergeLiveState(
        { self: { Other: 1 }, extra: true },
        { ObjectiveState: live },
      ),
    ).toEqual({ self: { Other: 1, ObjectiveState: live }, extra: true });
  });

  it("translates newswitch task updates", () => {
    expect(taskUpdateOf({ status: "running", progress: 40 })).toEqual({
      progress: 40,
    });
    expect(taskUpdateOf({ status: "completed", result: { ok: 1 } })).toEqual({
      returns: { ok: 1 },
      end: "done",
    });
    expect(taskUpdateOf({ status: "failed", error: "boom" })).toEqual({
      end: "failed",
      error: "boom",
    });
  });
});

describe("the jonda blok", () => {
  it("renders a button per mounted lens that switches to its slot", () => {
    const dispatchAction = vi.fn<BlokDispatchActionHandler>();
    const { roots } = normalizeBlokComponentTree(jonda.components);

    render(
      <BlokRenderer
        uiComponents={roots}
        initialState={mergeLiveState(jonda.demoState, {
          ObjectiveState: {
            slot: 1,
            name: "10x",
            magnification: 10,
            mounted_lenses: [lens(1, "10x"), lens(2, "40x")],
          },
        })}
        dispatchAction={dispatchAction}
      />,
    );

    expect(screen.getByText("Newswitch Handler")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "40x" }));

    expect(dispatchAction).toHaveBeenCalledTimes(1);
    const [action] = dispatchAction.mock.calls[0];
    expect(action).toMatchObject({
      dependency: "self",
      operation: "switch_objective",
    });
    expect(
      mapActionArguments(
        action.arguments,
        actionArgOrder(jonda, action.operation),
      ),
    ).toEqual({ ok: true, args: { slot: 2 } });
  });
});
