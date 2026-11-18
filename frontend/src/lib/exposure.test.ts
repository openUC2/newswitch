import { describe, expect, it } from "vitest";
import {
  EXPOSURE_SLIDER_STEPS,
  exposureToSlider,
  formatExposure,
  isActivePreset,
  sliderToExposure,
} from "./exposure";

/** Range of the HikRobot MV-CA023-10UM in seconds: 0.024 ms ... 10 s. */
const MIN = 0.000024;
const MAX = 10;

describe("formatExposure", () => {
  it.each([
    [0.000024, "0.024 ms"],
    [0.0025, "2.50 ms"],
    [0.0125, "12.5 ms"],
    [0.125, "125 ms"],
    [1.5, "1.50 s"],
    [10, "10.0 s"],
  ])("shows %s s as %s", (seconds, text) => {
    expect(formatExposure(seconds, "en")).toBe(text);
  });

  it("uses the language's decimal separator", () => {
    expect(formatExposure(0.0025, "de")).toBe("2,50 ms");
  });

  it("shows a missing value as a dash", () => {
    expect(formatExposure(Number.NaN, "en")).toBe("–");
  });
});

describe("exposure slider", () => {
  it("puts the camera's range on the slider's ends", () => {
    expect(exposureToSlider(MIN, MIN, MAX)).toBe(0);
    expect(exposureToSlider(MAX, MIN, MAX)).toBe(EXPOSURE_SLIDER_STEPS);
    expect(sliderToExposure(0, MIN, MAX)).toBe(MIN);
    expect(sliderToExposure(EXPOSURE_SLIDER_STEPS, MIN, MAX)).toBe(MAX);
  });

  it("is logarithmic: the middle is the geometric mean", () => {
    const middle = sliderToExposure(EXPOSURE_SLIDER_STEPS / 2, MIN, MAX);
    // 15.49 ms, rounded to three significant digits
    expect(middle / Math.sqrt(MIN * MAX)).toBeCloseTo(1, 2);
  });

  it("keeps values outside the range at its ends", () => {
    expect(exposureToSlider(MIN / 10, MIN, MAX)).toBe(0);
    expect(exposureToSlider(MAX * 10, MIN, MAX)).toBe(EXPOSURE_SLIDER_STEPS);
  });

  it("returns to the same position (within the rounding)", () => {
    for (let position = 0; position <= EXPOSURE_SLIDER_STEPS; position += 7) {
      const seconds = sliderToExposure(position, MIN, MAX);
      expect(exposureToSlider(seconds, MIN, MAX)).toBe(position);
    }
  });

  it("reaches a few ms in fine steps", () => {
    const position = exposureToSlider(0.005, MIN, MAX);
    expect(sliderToExposure(position, MIN, MAX)).toBeCloseTo(0.005, 4);
    const lower = sliderToExposure(position - 1, MIN, MAX);
    const upper = sliderToExposure(position + 1, MIN, MAX);
    expect(upper / lower).toBeLessThan(1.04); // neighbours within 2 % each
    expect(lower).toBeLessThan(0.005);
    expect(upper).toBeGreaterThan(0.005);
  });

  it("rounds to three significant digits in ms", () => {
    const seconds = sliderToExposure(611, MIN, MAX);
    const ms = seconds * 1000;
    expect(Number(ms.toPrecision(3))).toBe(ms);
  });

  it("falls back to linear without a positive minimum", () => {
    expect(exposureToSlider(5, 0, 10)).toBe(EXPOSURE_SLIDER_STEPS / 2);
    expect(sliderToExposure(EXPOSURE_SLIDER_STEPS / 2, 0, 10)).toBe(5);
  });

  it("copes with an empty range", () => {
    expect(exposureToSlider(0.01, 0.01, 0.01)).toBe(0);
    expect(sliderToExposure(500, 0.01, 0.01)).toBe(0.01);
  });
});

describe("isActivePreset", () => {
  it("accepts a preset within 1 %", () => {
    expect(isActivePreset(0.01005, 0.01)).toBe(true);
  });

  it("rejects a preset further away", () => {
    expect(isActivePreset(0.0105, 0.01)).toBe(false);
    expect(isActivePreset(0.1, 0.01)).toBe(false);
  });
});
