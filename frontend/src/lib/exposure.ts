/**
 * Exposure times as the UI shows and edits them.
 *
 * The backend keeps every exposure time in seconds (`Detector.current_exposure_time`,
 * `min_exposure_time`, `max_exposure_time`, `preset_exposure_times`, and the `exposure_time`
 * of the action `update_detector`). The UI shows milliseconds below one second and seconds
 * above, and its slider is logarithmic: a camera's range spans several decades
 * (e.g. 0.024 ms ... 10 s), so a linear slider could not reach "a few ms".
 */

/** Positions of the exposure slider: 0 is the minimum, this is the maximum. */
export const EXPOSURE_SLIDER_STEPS = 1000;

/** A preset counts as the current exposure within this relative difference. */
const PRESET_TOLERANCE = 0.01;

/**
 * `seconds` as text with three significant digits: "0.024 ms", "2.50 ms", "12.5 ms",
 * "125 ms", "1.50 s".
 *
 * @param seconds Exposure time in seconds.
 * @param locale Language for the number format; the browser's when left out.
 */
export function formatExposure(seconds: number, locale?: string): string {
  if (!Number.isFinite(seconds)) return "–";
  const format = (value: number, digits: number) =>
    new Intl.NumberFormat(locale, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(value);
  if (seconds >= 1) return `${format(seconds, seconds < 10 ? 2 : 1)} s`;
  const ms = seconds * 1000;
  const digits = ms < 1 ? 3 : ms < 10 ? 2 : ms < 100 ? 1 : 0;
  return `${format(ms, digits)} ms`;
}

/** `value` limited to `min ... max`. */
function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** `seconds` rounded to three significant digits in milliseconds (5.0123 ms -> 5.01 ms). */
function roundExposure(seconds: number): number {
  if (seconds <= 0) return 0;
  return Number((seconds * 1000).toPrecision(3)) / 1000;
}

/**
 * Slider position (0 ... `EXPOSURE_SLIDER_STEPS`) of an exposure time.
 *
 * Logarithmic between `min` and `max`; linear if `min` is not positive. Values outside the
 * range sit at its ends.
 *
 * @param seconds Exposure time in seconds.
 * @param min Shortest exposure of the camera in seconds.
 * @param max Longest exposure of the camera in seconds.
 */
export function exposureToSlider(
  seconds: number,
  min: number,
  max: number,
): number {
  if (!(max > min)) return 0;
  const value = clamp(seconds, min, max);
  const fraction =
    min > 0
      ? Math.log(value / min) / Math.log(max / min)
      : (value - min) / (max - min);
  return Math.round(fraction * EXPOSURE_SLIDER_STEPS);
}

/**
 * Exposure time in seconds at a slider position; the inverse of `exposureToSlider`.
 *
 * Rounded to three significant digits in milliseconds and kept within `min ... max`.
 *
 * @param position Slider position, 0 ... `EXPOSURE_SLIDER_STEPS`.
 * @param min Shortest exposure of the camera in seconds.
 * @param max Longest exposure of the camera in seconds.
 */
export function sliderToExposure(
  position: number,
  min: number,
  max: number,
): number {
  if (!(max > min)) return min;
  const fraction = clamp(position / EXPOSURE_SLIDER_STEPS, 0, 1);
  const seconds =
    min > 0
      ? min * Math.pow(max / min, fraction)
      : min + fraction * (max - min);
  return clamp(roundExposure(seconds), min, max);
}

/**
 * Whether `preset` is the current exposure: within 1 % of the preset.
 *
 * @param current Current exposure time in seconds.
 * @param preset Preset exposure time in seconds.
 */
export function isActivePreset(current: number, preset: number): boolean {
  return Math.abs(current - preset) <= PRESET_TOLERANCE * Math.abs(preset);
}
