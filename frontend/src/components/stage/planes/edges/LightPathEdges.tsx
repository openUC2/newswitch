import type { LightPathSnapshot } from "@/components/lightpathstate/LightPathStateRender";
import { useMemo } from "react";
import * as THREE from "three";

type KubeWithAffine = Extract<
  LightPathSnapshot["kubes"][number],
  { affine_matrix: number[][] }
>;

const toCenterPoint = (affineMatrix: number[][]): THREE.Vector3 => {
  const matrix = new THREE.Matrix4();
  const flat = affineMatrix.flat();

  matrix.set(
    flat[0],
    flat[1],
    flat[2],
    flat[3],
    flat[4],
    flat[5],
    flat[6],
    flat[7],
    flat[8],
    flat[9],
    flat[10],
    flat[11],
    flat[12],
    flat[13],
    flat[14],
    flat[15],
  );

  const position = new THREE.Vector3();
  const quaternion = new THREE.Quaternion();
  const scale = new THREE.Vector3();
  matrix.decompose(position, quaternion, scale);

  return position;
};

const normalizeIntensity = (value: number | null | undefined): number => {
  if (value === null || value === undefined) return 0.35;
  const normalized = value > 1 ? value / 100 : value;
  return THREE.MathUtils.clamp(normalized, 0, 1);
};

const hasAffineMatrix = (
  kube: LightPathSnapshot["kubes"][number],
): kube is KubeWithAffine => {
  return "affine_matrix" in kube;
};

export const LightPathEdges = ({ path }: { path: LightPathSnapshot }) => {
  const edges = useMemo(() => {
    const centersByKubeId = new Map(
      path.kubes
        .filter(hasAffineMatrix)
        .map((kube) => [kube.kube_id, toCenterPoint(kube.affine_matrix)]),
    );

    const yAxis = new THREE.Vector3(0, 1, 0);

    return path.edges
      .map((edge, index) => {
        const source = centersByKubeId.get(edge.source);
        const target = centersByKubeId.get(edge.target);

        if (!source || !target) return null;

        const direction = new THREE.Vector3().subVectors(target, source);
        const length = direction.length();
        if (length <= 0) return null;

        const midpoint = new THREE.Vector3()
          .addVectors(source, target)
          .multiplyScalar(0.5);

        const unitDirection = direction.clone().normalize();
        const quaternion = new THREE.Quaternion().setFromUnitVectors(
          yAxis,
          unitDirection,
        );

        const normalizedIntensity = normalizeIntensity(edge.intensity);
        const radius = 2 + normalizedIntensity * 2;
        const opacity = 0.25 + normalizedIntensity * 0.7;

        return {
          id: `${edge.source}-${edge.target}-${index}`,
          midpoint,
          quaternion,
          length,
          radius,
          opacity,
          emissiveIntensity: 0.15 + normalizedIntensity,
        };
      })
      .filter((value): value is NonNullable<typeof value> => value !== null);
  }, [path]);

  return (
    <>
      {edges.map((edge) => (
        <mesh
          key={edge.id}
          position={edge.midpoint}
          quaternion={edge.quaternion}
        >
          <cylinderGeometry
            args={[edge.radius, edge.radius, edge.length, 16]}
          />
          <meshStandardMaterial
            color="#dadada"
            transparent
            opacity={edge.opacity}
            emissive="#d9d9d9"
            emissiveIntensity={edge.emissiveIntensity}
            roughness={0.35}
            metalness={0.15}
          />
        </mesh>
      ))}
    </>
  );
};
