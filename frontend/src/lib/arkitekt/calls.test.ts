import { describe, expect, it } from "vitest";
import { evaluateCall, validatorAccepts, type UtilCall } from "./calls";

// `withValidator("len(value) > 0")`, as the backend sends it.
const nonEmpty: UtilCall = {
  operation: "gt",
  arguments: [
    {
      key: "a",
      utilCall: {
        operation: "len",
        arguments: [{ key: "a", valuePath: "value" }],
      },
    },
    { key: "b", valueLiteral: 0 },
  ],
};

describe("calls", () => {
  it("evaluates a nested call against the port's own value", () => {
    expect(validatorAccepts(nonEmpty, { value: [1] })).toBe(true);
    expect(validatorAccepts(nonEmpty, { value: [] })).toBe(false);
    expect(validatorAccepts(nonEmpty, { value: null })).toBe(false);
  });

  it("reads other ports from the dependencies", () => {
    const below: UtilCall = {
      operation: "lt",
      arguments: [
        { key: "a", valuePath: "value" },
        { key: "b", valuePath: "max" },
      ],
    };
    expect(
      validatorAccepts(below, { value: 3, dependencies: { max: 5 } }),
    ).toBe(true);
    expect(
      validatorAccepts(below, { value: 7, dependencies: { max: 5 } }),
    ).toBe(false);
  });

  it("lets a value pass when an operation is unknown", () => {
    const unknown: UtilCall = { operation: "fmt.date", arguments: [] };
    expect(evaluateCall(unknown, { value: 1 })).toBeUndefined();
    expect(validatorAccepts(unknown, { value: 1 })).toBe(true);
  });
});
