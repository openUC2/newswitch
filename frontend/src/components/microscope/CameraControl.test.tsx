import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  exposureToSlider,
  formatExposure,
  sliderToExposure,
} from "@/lib/exposure";
import { CameraControl } from "./CameraControl";

/**
 * The exposure slider of `CameraControl` (exposure in seconds, logarithmic positions).
 *
 * Regression: the slider was given the server's exposure while the panel re-rendered on every
 * move (to show the dragged value), so `OptimisticSlider` reset the thumb on each move, and
 * Radix, seeing no change at the end of a drag, never committed: the slider could not be used.
 */

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

/** Range of the HikRobot MV-CA023-10UM in seconds: 0.024 ms ... 10 s. */
const MIN = 0.000024;
const MAX = 10;
const CURRENT = 0.01;

const { updateDetector } = vi.hoisted(() => ({
  // never answers, so the panel stays in the state right after the commit
  updateDetector: vi.fn(() => new Promise<unknown>(() => {})),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { resolvedLanguage: "en" },
  }),
}));

vi.mock("@/apps/default/hooks/actions", () => ({
  useActivateDetector: () => ({ assign: vi.fn(), isLoading: false }),
  useDeactivateDetector: () => ({ assign: vi.fn(), isLoading: false }),
  useUpdateDetector: () => ({ call: updateDetector, isLoading: false }),
}));

vi.mock("@/apps/default/hooks/states", () => ({
  useCameraState: () => ({
    loading: false,
    data: {
      detectors: [
        {
          slot: 2,
          name: "MV-CA023-10UM",
          is_active: true,
          width: 1920,
          height: 1200,
          pixel_size_um: 5.86,
          current_exposure_time: CURRENT,
          min_exposure_time: MIN,
          max_exposure_time: MAX,
          preset_exposure_times: [0.01, 0.1],
          current_gain: 0,
          min_gain: 0,
          max_gain: 24,
        },
      ],
    },
  }),
}));

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  // Radix measures the slider with a ResizeObserver, which jsdom does not have
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  updateDetector.mockClear();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

/** Render the panel and open the detector's controls. */
function renderExpanded() {
  act(() => root.render(<CameraControl />));
  const name = [...container.querySelectorAll("span")].find(
    (span) => span.textContent === "MV-CA023-10UM",
  );
  expect(name).toBeDefined();
  act(() => name!.click());
}

/** The exposure slider's thumb: the first slider of the panel. */
function exposureThumb(): HTMLElement {
  const thumb = container.querySelector<HTMLElement>('[role="slider"]');
  expect(thumb).not.toBeNull();
  return thumb!;
}

describe("CameraControl exposure slider", () => {
  it("starts at the detector's exposure", () => {
    renderExpanded();
    expect(exposureThumb().getAttribute("aria-valuenow")).toBe(
      String(exposureToSlider(CURRENT, MIN, MAX)),
    );
    expect(container.textContent).toContain(formatExposure(CURRENT, "en"));
  });

  it("keeps a moved thumb where it is and sends that exposure in seconds", () => {
    renderExpanded();
    const start = exposureToSlider(CURRENT, MIN, MAX);
    const expected = sliderToExposure(start + 1, MIN, MAX);

    act(() => {
      exposureThumb().dispatchEvent(
        new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }),
      );
    });

    expect(exposureThumb().getAttribute("aria-valuenow")).toBe(
      String(start + 1),
    );
    expect(updateDetector).toHaveBeenCalledWith({
      slot: 2,
      exposure_time: expected,
    });
    expect(container.textContent).toContain(formatExposure(expected, "en"));
  });
});
