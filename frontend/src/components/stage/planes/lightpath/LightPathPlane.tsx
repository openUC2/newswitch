import {
  LightPathSchema,
  useLightPathState,
} from "@/apps/default/hooks/states";
import { useKubeStore } from "@/store/kubeStore";
import { useModeStore } from "@/store/modeStore";
import { Suspense, useEffect, useRef } from "react";
import * as THREE from "three";
import { type z } from "zod";
import { ObjectiveTurretKubePlane } from "../kubes/ObjectiveTurretKubePlane";
import { LightPathEdges } from "./edges/LightPathEdges";
import { DetectorKubePlane } from "./kubes/DetectorKubePlane";
import { DichroicKubePlane } from "./kubes/DichroicKube";
import { FilterBankKubePlane } from "./kubes/FilterBankKubePlane";
import { FilterKubePlane } from "./kubes/FilterKubePlane";
import { IlluminationKubePlane } from "./kubes/IlluminationKubePlane";
import { ObjectiveKubePlane } from "./kubes/ObjectiveKubePlane";
import { StageKubePlane } from "./kubes/StageKubePlane";

export type LightPath = z.infer<typeof LightPathSchema>;

// --- The High-Performance Outline Wrapper ---
export const InvertedHullOutline = ({
  children,
  color = "#10b981", // Emerald Glow
  thickness = 1.05, // Inflate the hull by 5%
  enabled = true,
}: {
  children: React.ReactNode;
  color?: string;
  thickness?: number;
  enabled?: boolean;
}) => {
  const groupRef = useRef<THREE.Group>(null);

  useEffect(() => {
    if (!enabled || !groupRef.current) return;

    const outlines: THREE.Mesh[] = [];

    // Traverse the children to find actual 3D meshes
    groupRef.current.traverse((child) => {
      // We only want solid meshes. We ignore existing outlines, Html, or light cones
      if (child instanceof THREE.Mesh && !child.userData.isOutline) {
        // Skip highly transparent meshes (like the light cone indicators)
        if (child.material.transparent && child.material.opacity < 0.5) return;

        // Clone the geometry and wrap it in the inverted hull material
        const outlineMesh = new THREE.Mesh(child.geometry);
        outlineMesh.material = new THREE.MeshBasicMaterial({
          color: color,
          side: THREE.BackSide, // The magic trick: renders only the inside!
          depthWrite: true, // Occludes properly behind other objects
        });

        // Inflate the mesh slightly
        outlineMesh.scale.copy(child.scale).multiplyScalar(thickness);

        // Match the original position and rotation
        outlineMesh.position.copy(child.position);
        outlineMesh.rotation.copy(child.rotation);

        // Tag it so we don't accidentally clone it again
        outlineMesh.userData.isOutline = true;

        // Attach it to the same parent as the original mesh
        child.parent?.add(outlineMesh);
        outlines.push(outlineMesh);
      }
    });

    // Cleanup: Remove the hulls when deselected or unmounted
    return () => {
      outlines.forEach((mesh) => {
        mesh.parent?.remove(mesh);
        (mesh.material as THREE.Material).dispose();
        // Geometry is shared, so we don't dispose of it here
      });
    };
  }, [enabled, color, thickness]);

  return <group ref={groupRef}>{children}</group>;
};

// --- Main Light Path Plane Component ---
export const LightPathPlane = ({ path }: { path: LightPath }) => {
  const selectedKube = useKubeStore((s) => s.selectedKube);
  const setSelectedKube = useKubeStore((s) => s.setSelectedKube);

  return (
    <>
      <LightPathEdges path={path} />
      {path.kubes.map((kube) => {
        const isSelected = selectedKube?.kube_id === kube.kube_id;

        return (
          <Suspense key={kube.kube_id} fallback={<></>}>
            <group
              name={kube.kube_id}
              onClick={(e) => {
                e.stopPropagation();
                if (isSelected) {
                  setSelectedKube(null);
                } else {
                  setSelectedKube(kube);
                }
              }}
            >
              {/* Drop in the Inverted Hull Wrapper */}
              <InvertedHullOutline enabled={isSelected}>
                {(() => {
                  switch (kube.__identifier) {
                    case "@newswitch/objective_turret_kube":
                      return <ObjectiveTurretKubePlane data={kube} />;
                    case "@newswitch/objective_kube":
                      return <ObjectiveKubePlane data={kube} />;
                    case "@newswitch/detector_kube":
                      return <DetectorKubePlane data={kube} />;
                    case "@newswitch/filter_kube":
                      return <FilterKubePlane data={kube} />;
                    case "@newswitch/filter_bank_kube":
                      return <FilterBankKubePlane data={kube} />;
                    case "@newswitch/illumination_kube":
                      return <IlluminationKubePlane data={kube} />;
                    case "@newswitch/stage_kube":
                      return <StageKubePlane data={kube} />;
                    case "@newswitch/dichroic_kube":
                      return <DichroicKubePlane data={kube} />;
                    case "@newswitch/generic_kube":
                      return null;
                    default:
                      return null;
                  }
                })()}
              </InvertedHullOutline>
            </group>
          </Suspense>
        );
      })}
    </>
  );
};

// --- Scene View Toggle ---
export const CurrentLightPathPlane = () => {
  const { data: lightpath } = useLightPathState();
  const currentMode = useModeStore((state) => state.interactionMode);
  const displayMode = useModeStore((state) => state.displayMode);

  const randomlySelectedLightPath = lightpath?.light_paths.at(0); // Light Path should be more generic (not dtector specific)

  if (currentMode !== "META" || displayMode !== "3D") return null;

  return (
    <Suspense fallback={<></>}>
      {randomlySelectedLightPath && (
        <LightPathPlane path={randomlySelectedLightPath} />
      )}
    </Suspense>
  );
};
