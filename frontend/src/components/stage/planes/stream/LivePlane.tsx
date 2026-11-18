import type { Detector } from "@/apps/default/hooks/actions";
import { useCurrentAffineTransform } from "@/hooks/useCurrentAffineTransform";
import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import { DoubleSide, Matrix4, Mesh } from "three";
import { useH264LiveTexture } from "../../hooks/useH264LiveTexture";

export const LivePlane = (props: { detector: Detector }) => {
  const meshRef = useRef<Mesh>(null);

  const { texture: liveTexture } = useH264LiveTexture({
    detector: props.detector,
  });
  const affine = useCurrentAffineTransform();
  // The plane keeps the detector's aspect ratio (the stream itself is 640 x 480)
  const { width, height } = props.detector;
  const aspect = width > 0 && height > 0 ? height / width : 1;

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

    // Apply the 20um scale relative to the affine transform
    const liveTextureSizeUm = 1024;
    const scaleM = new Matrix4().makeScale(
      liveTextureSizeUm,
      liveTextureSizeUm * aspect,
      1,
    );
    return m.multiply(scaleM);
  }, [affine, aspect]);

  // NOTE: the per-frame `needsUpdate` flag for the video texture now lives inside
  // useH264LiveTexture, which owns the texture.
  useFrame(() => {
    if (meshRef.current) {
      meshRef.current.matrix.copy(stageMatrix);
      meshRef.current.matrixWorldNeedsUpdate = true;
    }
  });

  return (
    <mesh ref={meshRef} matrixAutoUpdate={false}>
      <planeGeometry args={[1, 1]} />
      {/* unlit: the image shows as streamed, not darkened by the scene's lights */}
      <meshBasicMaterial
        map={liveTexture}
        side={DoubleSide}
        toneMapped={false}
      />
    </mesh>
  );
};
