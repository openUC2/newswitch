import { useRef, useLayoutEffect } from "react";
import { useLoader } from "@react-three/fiber";
import { TextureLoader, DoubleSide, Mesh, Matrix4 } from "three";
import type { ExpanseState } from "@/apps/default/hooks/states/ExpanseState";
import { useTransport } from "@/lib/rekuest/transport/transport-context";
import { useSelectionStore } from "@/store/imageStore";
import { withToken } from "@/lib/auth/authFetch";
// import { useTransport } from '../transport/TransportProvider';
// import type { ExpanseState } from '../store/types';

export const ImagePlane = ({
  image,
  index,
}: {
  image: ExpanseState["current_images"][0];
  index: number;
}) => {
  const meshRef = useRef<Mesh>(null);
  const { apiEndpoint } = useTransport();
  const setSelectedImageId = useSelectionStore((s) => s.setSelectedImageId);

  const baseUrl = apiEndpoint.replace(/\/$/, "");
  // three.js loads textures by assigning to an Image's src, which cannot carry an
  // Authorization header, so the token goes in the query string.
  const url = withToken(`${baseUrl}/files/${encodeURIComponent(image.id)}`);

  // Load the texture from the generated URL
  // Note: Ensure this component is wrapped in a <Suspense> boundary in your parent component
  const texture = useLoader(TextureLoader, url);

  useLayoutEffect(() => {
    if (!meshRef.current || !image.metadata?.affine_matrix) return;

    // Flatten the float[][] into a 1D float[]
    const flatMatrix = image.metadata.affine_matrix.flat();

    // Ensure we have exactly 16 elements before applying
    if (flatMatrix.length === 16) {
      // Three.js .set() takes elements in row-major order,
      // which maps perfectly to a flattened standard 2D array.
      const matrix = new Matrix4().set(
        flatMatrix[0],
        flatMatrix[1],
        flatMatrix[2],
        flatMatrix[3],
        flatMatrix[4],
        flatMatrix[5],
        flatMatrix[6],
        flatMatrix[7],
        flatMatrix[8],
        flatMatrix[9],
        flatMatrix[10] + index,
        flatMatrix[11],
        flatMatrix[12],
        flatMatrix[13],
        flatMatrix[14],
        flatMatrix[15],
      );

      // Apply the affine matrix directly to the mesh
      meshRef.current.matrix.copy(matrix);
      meshRef.current.matrixWorldNeedsUpdate = true;
    } else {
      console.warn(
        "[ImagePlane] Invalid affine matrix dimensions:",
        flatMatrix.length,
      );
    }
    // `index` is baked into the matrix (z-offset) below, so it has to be a dependency -
    // without it the plane kept its old z-offset when its stacking index changed.
  }, [image.metadata?.affine_matrix, index]);

  return (
    <mesh
      ref={meshRef}
      matrixAutoUpdate={false}
      onClick={() => setSelectedImageId(image.id)}
    >
      <planeGeometry args={[1, 1]} />
      <meshBasicMaterial
        map={texture}
        side={DoubleSide}
        transparent={true}
        toneMapped={false}
      />
    </mesh>
  );
};

export default ImagePlane;
