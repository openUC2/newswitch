import type { Detector } from "@/apps/default/hooks/states/DetectorState";
import {
  planeOf,
  toMatrix4,
  useDetectorPlacement,
} from "@/lib/microscope/space";
import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import { DoubleSide, Matrix4, Mesh } from "three";
import { useLiveFrameTexture } from "../../hooks/useLiveFrameTexture";

/**
 * A detector's live image, where its pixels are on the sample now.
 *
 * The plane is one unit square; it is stretched over the image's pixels (column, row: row 0 at
 * the image's top, which is the texture's top) and those are placed by the detector's placement.
 * The live view sends smaller frames than the detector delivers: what the plane covers is the
 * detector's image, whatever size the texture is.
 */
export const LivePlane = (props: { detector: Detector }) => {
  const meshRef = useRef<Mesh>(null);
  const liveTexture = useLiveFrameTexture(props.detector.name);
  const placement = useDetectorPlacement(props.detector.name);
  const { width, height } = planeOf(props.detector);

  const placed = useMemo(() => {
    const overPixels = new Matrix4()
      .makeTranslation((width - 1) / 2, (height - 1) / 2, 0)
      .multiply(new Matrix4().makeScale(width, -height, 1));
    return toMatrix4(placement?.to_sample).multiply(overPixels);
  }, [placement, width, height]);

  useFrame(() => {
    if (meshRef.current) {
      meshRef.current.matrix.copy(placed);
      meshRef.current.matrixWorldNeedsUpdate = true;
    }
  });

  if (!liveTexture || !placement) return null;

  return (
    <mesh ref={meshRef} matrixAutoUpdate={false}>
      <planeGeometry args={[1, 1]} />
      <meshStandardMaterial
        map={liveTexture}
        side={DoubleSide}
        toneMapped={false}
      />
    </mesh>
  );
};
