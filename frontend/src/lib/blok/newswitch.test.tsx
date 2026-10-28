// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import jondaPayload from "./jonda.fixture.json";
import { SwitchObjectiveArgsSchema } from "@/apps/default/hooks/actions/switchObjective";
import {
  actionArgOrder,
  blokModel,
  blokRoots,
  foreignDependencyKeys,
  mapActionArguments,
  mergeLiveState,
  selfStateKeys,
  taskUpdateOf,
  type NewswitchBlokDeclaration,
} from "./newswitch";
import BlokRenderer from "@arkitektio/bsx/renderer/BlokRenderer";
import { locksOf } from "./microscope/locks";
import { newswitchBlokCatalog } from "./microscope/catalog";
import { lockedActionKey } from "@arkitektio/bsx/renderer/runtime/index";
import { type BlokDispatchActionHandler } from "@arkitektio/bsx/renderer/runtime/index";

// The jonda blok exactly as the backend serves it at /schemas/bloks (blok language v2).
const jonda = jondaPayload as unknown as NewswitchBlokDeclaration;
const jondaRoots = blokRoots(jonda);
const jondaModel = blokModel(jonda, jondaRoots);

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

  it("names an argument spelled by position by the blok's demand", () => {
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

  it("draws the blok's demo until a state is live", () => {
    expect(jondaModel).toMatchObject({
      deps: { self: { ObjectiveState: { mounted_lenses: [] } } },
    });
    expect(mergeLiveState(jondaModel, { ObjectiveState: null })).toBe(
      jondaModel,
    );
  });

  it("lays live state over the demo, under deps.self", () => {
    const live = { slot: 1, name: "a", magnification: 4, mounted_lenses: [] };
    expect(
      mergeLiveState(
        { deps: { self: { Other: 1 } }, extra: true },
        { ObjectiveState: live },
      ),
    ).toEqual({
      deps: { self: { Other: 1, ObjectiveState: live } },
      extra: true,
    });
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
    render(
      <BlokRenderer
        catalog={newswitchBlokCatalog}
        uiComponents={jondaRoots}
        initialState={mergeLiveState(jondaModel, {
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

describe("locked controls", () => {
  const renderJonda = (lockedActions?: ReadonlyMap<string, string>) =>
    render(
      <BlokRenderer
        catalog={newswitchBlokCatalog}
        uiComponents={jondaRoots}
        initialState={mergeLiveState(jondaModel, {
          ObjectiveState: {
            slot: 1,
            name: "10x",
            magnification: 10,
            mounted_lenses: [lens(1, "10x"), lens(2, "40x")],
          },
        })}
        lockedActions={lockedActions}
      />,
    );

  it("marks a control whose action a held lock keeps from running", () => {
    renderJonda(
      new Map([
        [lockedActionKey("self", "switch_objective"), "objective is held"],
      ]),
    );
    const marker = screen
      .getByRole("button", { name: "40x" })
      .closest("[data-locked]");
    expect(marker).toBeTruthy();
    expect(marker?.getAttribute("title")).toBe("objective is held");
    // Marked, not disabled: what a locked control looks like is the blok's call.
    expect(
      (screen.getByRole("button", { name: "40x" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });

  it("leaves controls unmarked while nothing they need is locked", () => {
    renderJonda(
      new Map([[lockedActionKey("self", "move_stage"), "stage is held"]]),
    );
    expect(
      screen.getByRole("button", { name: "40x" }).closest("[data-locked]"),
    ).toBeNull();
  });
});

describe("microscope panel locks", () => {
  it("are the locks the panel's actions take", () => {
    expect(locksOf(["move_stage", "move_home"])).toContain("stage_position");
    expect(locksOf(["no_such_action"])).toEqual([]);
  });
});
