import type { LightPathSnapshot } from "@/components/lightpathstate/LightPathStateRender";
import { Suspense, useEffect, useRef } from "react";
import * as THREE from "three";
import { DetectorKubePlane } from "./kubes/DetectorKubePlane";
import { ObjectiveKubePlane } from "./kubes/ObjectiveKubePlane";
import { FilterKubePlane } from "./kubes/FilterKubePlane";
import { IlluminationKubePlane } from "./kubes/IlluminationKubePlane";
import { StageKubePlane } from "./kubes/StageKubePlane";
import { DichroicKubePlane } from "./kubes/DichroicKube";
import { LightPathEdges } from "./edges/LightPathEdges";
import { useModeStore } from "@/store/modeStore";
import { useKubeStateStore } from "@/store/kubeStateStore";
import { useSelectedFrame } from "../hooks/useSelectedFrame";

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
export const LightPathStatePlane = ({ path }: { path: LightPathSnapshot }) => {
  const selectedKubeState = useKubeStateStore((s) => s.selectedKubeState);
  const setKubeState = useKubeStateStore((s) => s.setSelectedKubeState);

  return (
    <>
      <LightPathEdges path={path} />
      {path.kubes.map((kube) => {
        // NOTE: previously also compared `selectedKubeState?.id`, which does not exist on
        // any kube state variant (they are keyed by `kube_id`); that clause was always false.
        const isSelected = selectedKubeState?.kube_id === kube.kube_id;

        return (
          <Suspense key={kube.kube_id} fallback={<></>}>
            <group
              name={kube.kube_id}
              onClick={(e) => {
                e.stopPropagation();
                if (isSelected) {
                  setKubeState(null);
                } else {
                  setKubeState(kube);
                }
              }}
            >
              {/* Drop in the Inverted Hull Wrapper */}
              <InvertedHullOutline enabled={isSelected}>
                {(() => {
                  switch (kube.__identifier) {
                    case "@newswitch/objective_kube_state":
                      return <ObjectiveKubePlane data={kube} />;
                    case "@newswitch/detector_kube_state":
                      return <DetectorKubePlane data={kube} />;
                    case "@newswitch/filter_kube_state":
                      return <FilterKubePlane data={kube} />;
                    case "@newswitch/illumination_kube_state":
                      return <IlluminationKubePlane data={kube} />;
                    case "@newswitch/stage_kube_state":
                      return <StageKubePlane data={kube} />;
                    case "@newswitch/dichroic_kube_state":
                      return <DichroicKubePlane data={kube} />;
                    case "@newswitch/generic_kube_state":
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
export const CurrentFrameLightPathPlane = () => {
  const selectedFrame = useSelectedFrame();
  const currentMode = useModeStore((state) => state.interactionMode);
  const displayMode = useModeStore((state) => state.displayMode);

  if (currentMode !== "META" || displayMode !== "3D") return null;

  return (
    <Suspense fallback={<></>}>
      {selectedFrame?.metadata?.light_state && (
        <LightPathStatePlane path={selectedFrame.metadata.light_state} />
      )}
    </Suspense>
  );
};
