import type { Detector } from "@/apps/default/hooks/actions";
import { useCurrentAffineTransform } from "@/hooks/useCurrentAffineTransform";
import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import { DoubleSide, Matrix4, Mesh } from "three";
import { useLiveFrameTexture } from "../../hooks/useLiveFrameTexture";

export const LivePlane = (props: { detector: Detector }) => {
  const meshRef = useRef<Mesh>(null);

  const liveTexture = useLiveFrameTexture(props.detector.slot);
  const imageWidth = liveTexture?.image.width ?? 1;
  const imageHeight = liveTexture?.image.height ?? 1;
  const affine = useCurrentAffineTransform();

  const stageMatrix = useMemo(() => {
    // Ensure we are reading the 4x4 array correctly.
    // Matrix4.set is (n11, n12, n13, n14...)
    const m = new Matrix4();
    if (affine && affine.length === 4) {
      m.set(
        affine[0][0],
        affine[0][1],
        affine[0][2],
        affine[0][3],
        affine[1][0],
        affine[1][1],
        affine[1][2],
        affine[1][3],
        affine[2][0],
        affine[2][1],
        affine[2][2],
        affine[2][3],
        affine[3][0],
        affine[3][1],
        affine[3][2],
        affine[3][3],
      );
    }

    // The longer side is this large relative to the affine transform; the other follows
    // from the image, so it is not stretched.
    const liveTextureSizeUm = 1024;
    const longerSide = Math.max(imageWidth, imageHeight);
    const scaleM = new Matrix4().makeScale(
      (liveTextureSizeUm * imageWidth) / longerSide,
      (liveTextureSizeUm * imageHeight) / longerSide,
      1,
    );
    return m.multiply(scaleM);
  }, [affine, imageWidth, imageHeight]);

  useFrame(() => {
    if (meshRef.current) {
      meshRef.current.matrix.copy(stageMatrix);
      meshRef.current.matrixWorldNeedsUpdate = true;
    }
  });

  if (!liveTexture) return null;

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
