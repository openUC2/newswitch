// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import * as z from "zod";
import BlokRenderer from "./BlokRenderer";
import { defaultBlokCatalog } from "./catalog";
import { createBlokCatalog } from "./runtime/functions";
import { createBlokComponent } from "./runtime";

afterEach(cleanup);

describe("BlokRenderer", () => {
  it("resolves a catalog function on the first render", () => {
    render(
      <BlokRenderer
        initialState={{ step: 0 }}
        uiComponents={[
          {
            id: "back",
            component: "Button",
            props: [
              {
                key: "disabled",
                util_call: {
                  operation: "eq",
                  arguments: [
                    { key: "a", value_path: "step" },
                    { key: "b", value_literal: 0 },
                  ],
                },
              },
            ],
          },
        ]}
      />,
    );

    expect(screen.queryByText(/No blok function catalog/)).toBeNull();
    expect((screen.getByRole("button") as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it("renders a blok opened inside another, whose ids repeat the outer one's", () => {
    // A card opened from a scene is its own blok: its root `div` is not the outer `div`.
    const card = [
      {
        id: "div",
        component: "Text",
        props: [{ key: "text", static_value: "card" }],
      },
    ];
    const Opened = createBlokComponent(
      { name: "Opened", schema: z.object({}) },
      () => <BlokRenderer uiComponents={card} chrome="none" />,
    );
    const catalog = createBlokCatalog(
      "test",
      [...defaultBlokCatalog.components.values(), Opened],
      defaultBlokCatalog.functionDefinitions,
    );
    render(
      <BlokRenderer
        catalog={catalog}
        chrome="none"
        uiComponents={[
          {
            id: "div",
            component: "div",
            props: [],
            children: [{ id: "opened", component: "Opened", props: [] }],
          },
        ]}
      />,
    );
    expect(screen.queryByText(/Recursive child reference/)).toBeNull();
    expect(screen.getByText("card")).toBeTruthy();
  });
});
