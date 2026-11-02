import { useDetectorState } from "@/apps/default/hooks/states/DetectorState";
import type { Detector } from "@/apps/default/hooks/states/DetectorState";
import { useSpaceState } from "@/apps/default/hooks/states/SpaceState";
import { Matrix4, Vector3 } from "three";

/**
 * Where things are. The scene is the sample's frame, in micrometres: the server places every
 * detector's pixels in it (`SpaceState.detectors[name].to_sample`: column, row and plane to
 * sample micrometres), every frame taken (its metadata's affine, the same map then), and the
 * stage through the mount (`SpaceState.mount`, stage to sample). Nothing is placed in here.
 */

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

/** The detector the view is of: the first that is on, else the first. */
export const useViewDetector = (): Detector | undefined => {
  const { data } = useDetectorState({ subscribe: true });
  const detectors = data?.detectors ?? [];
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

/** Stage micrometres to sample micrometres: where what is mounted sits. */
export const useMount = (): Matrix4 => {
  const { data } = useSpaceState({ subscribe: true });
  return toMatrix4(data?.mount);
};
