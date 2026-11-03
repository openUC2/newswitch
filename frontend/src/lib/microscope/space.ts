import { useDetectorState } from "@/apps/default/hooks/states/DetectorState";
import type { Detector } from "@/apps/default/hooks/states/DetectorState";
import { useSpaceState } from "@/apps/default/hooks/states/SpaceState";
import { Matrix4, Vector3 } from "three";
import { useSceneSample } from "./sampleContext";

/**
 * Where things are. A scene is one sample's frame, in micrometres (`useSceneSample`): the server
 * places every detector's pixels in its own sample's (`SpaceState.detectors[name].to_sample`:
 * column, row and plane to sample micrometres, and `.sample`), every frame taken (its metadata's
 * affine and sample), and each stage through its sample's mount (`SpaceState.samples[cube].mount`,
 * stage to sample). Nothing is placed in here.
 */

/** Whether `detector` images light: it measures light, along a y and an x in space. A probe does
 * not (a thermometer, an electrode array), however its places are laid out. */
export const deliversImages = (detector: Detector): boolean =>
  detector.measures_light !== false &&
  ["y", "x"].every((name) =>
    detector.axes.some((axis) => axis.name === name && axis.domain === "space"),
  );

/** A 4x4 as the server sends it (rows), as three.js takes it. */
export const toMatrix4 = (rows?: number[][] | null): Matrix4 => {
  const matrix = new Matrix4();
  if (rows && rows.length === 4) {
    matrix.set(...(rows.flat() as Parameters<Matrix4["set"]>));
  }
  return matrix;
};

/** How many values an image of `detector` has along y and x: its windows, binned. */
export const planeOf = (
  detector: Detector,
): { width: number; height: number } => {
  const along = (name: string) =>
    detector.axes.find((axis) => axis.name === name)?.delivered_size ?? 1;
  return { width: along("x"), height: along("y") };
};

/** Where `detector`'s pixels are on the sample now; undefined until the server says. */
export const useDetectorPlacement = (detector: string) => {
  const { data } = useSpaceState({ subscribe: true });
  return data?.detectors?.[detector];
};

/** Whether `detector` sees the scene's sample now. One a switch sends no light to is placed
 * nowhere, and sees none; until the server says, every one might. */
export const useSeesScene = (): ((detector: string) => boolean) => {
  const sample = useSceneSample();
  const { data } = useSpaceState({ subscribe: true });
  return (detector: string) => {
    if (data === undefined || data === null) return true;
    const seen =
      data.detectors?.[detector]?.sample ?? data.points?.[detector]?.sample;
    return seen === "" || (seen !== undefined && seen === sample);
  };
};

/** The detector the view is of: of the scene's sample, the first imaging one that is on, else the
 * first imaging one. */
export const useViewDetector = (): Detector | undefined => {
  const { data } = useDetectorState({ subscribe: true });
  const sees = useSeesScene();
  const detectors = (data?.detectors ?? []).filter(
    (d) => deliversImages(d) && sees(d.name),
  );
  return detectors.find((d) => d.is_active) ?? detectors[0];
};

/** How wide and high what the view's detector sees is, on the sample, in micrometres. */
export const useViewField = ():
  | { width: number; height: number }
  | undefined => {
  const detector = useViewDetector();
  const placement = useDetectorPlacement(detector?.name ?? "");
  if (!detector || !placement) return undefined;
  const { width, height } = planeOf(detector);
  const [alongX, alongY] = placement.pixel_um;
  return { width: alongX * width, height: alongY * height };
};

/** The sample point at the middle of the view's image. */
export const useLookingAt = (): Vector3 | undefined => {
  const detector = useViewDetector();
  const placement = useDetectorPlacement(detector?.name ?? "");
  if (!detector || !placement) return undefined;
  const { width, height } = planeOf(detector);
  return new Vector3((width - 1) / 2, (height - 1) / 2, 0).applyMatrix4(
    toMatrix4(placement.to_sample),
  );
};

/** Where each detector that measures at one point beside the scene's sample measures, with what it
 * read last. */
export const useMeasuredPoints = () => {
  const { data: space } = useSpaceState({ subscribe: true });
  const { data: detectors } = useDetectorState({ subscribe: true });
  const sample = useSceneSample();
  const points = Object.values(space?.points ?? {}).filter(
    (point) => !point.sample || point.sample === sample,
  );
  return points.map((point) => {
    const detector = detectors?.detectors.find(
      (d) => d.name === point.detector,
    );
    return {
      ...point,
      reading: detector?.reading ?? null,
      unit: detector?.unit ?? "",
    };
  });
};

/** The scene's sample: its mount, what it is mounted on and what that looks like. */
export const useSampleSpace = () => {
  const { data } = useSpaceState({ subscribe: true });
  const sample = useSceneSample();
  return sample === undefined ? undefined : data?.samples?.[sample];
};

/** The scene's stage micrometres to its sample micrometres: where what is mounted sits. */
export const useMount = (): Matrix4 => toMatrix4(useSampleSpace()?.mount);
