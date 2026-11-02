import { useLookingAt } from "@/lib/microscope/space";
import { useSceneSample } from "@/lib/microscope/sampleContext";
import { useModeStore } from "@/store/modeStore";
import {
  MapControls,
  OrbitControls,
  OrthographicCamera,
  PerspectiveCamera,
} from "@react-three/drei";
import { useThree } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import type { Camera, Vector3 } from "three";

type Controls = { object: Camera; target: Vector3; update: () => void };

/**
 * Brings the camera over where the view's camera looks on its sample: once for each sample and
 * each of 2D and 3D, so that what is mounted (a slide's middle is 37 mm from its corner) is in
 * view, and the scene is not taken from under whoever is moving around in it.
 */
const CameraFocus = () => {
  const looking = useLookingAt();
  const sample = useSceneSample();
  const displayMode = useModeStore((s) => s.displayMode);
  const controls = useThree((s) => s.controls) as unknown as Controls | null;
  const camera = useThree((s) => s.camera);
  const centred = useRef<string | null>(null);
  useEffect(() => {
    // Only once the controls drive the camera in use: a 2D/3D switch makes both anew.
    if (!looking || !controls || controls.object !== camera) return;
    const key = `${sample}:${displayMode}`;
    if (centred.current === key) return;
    centred.current = key;
    const offset = camera.position.clone().sub(controls.target);
    controls.target.set(looking.x, looking.y, 0);
    camera.position.set(looking.x + offset.x, looking.y + offset.y, offset.z);
    controls.update();
  }, [looking, controls, camera, sample, displayMode]);
  return null;
};

export const CameraController = () => {
  const interactionMode = useModeStore((s) => s.interactionMode);
  const displayMode = useModeStore((s) => s.displayMode);

  return (
    <>
      {/* Camera Rig */}
      {displayMode === "3D" ? (
        <PerspectiveCamera
          makeDefault
          position={[0, -200, 200]}
          fov={45}
          up={[0, 0, 1]}
          // Extend the clipping planes to prevent geometry from being cut off
          near={0.1}
          far={10000}
        />
      ) : (
        <OrthographicCamera
          makeDefault
          zoom={5}
          position={[0, 0, 500]}
          up={[0, 0, 1]}
          // Extend the clipping planes for the orthographic view as well
          near={0.1}
          far={10000}
        />
      )}

      {/* Orbit Controls 
                Disable panning/rotating when scanning so the screen doesn't drag while drawing.
            */}
      {displayMode === "3D" ? (
        <OrbitControls
          makeDefault
          enableRotate={displayMode === "3D"}
          enablePan={interactionMode === "PAN"}
          enableZoom={true}
        />
      ) : (
        <MapControls makeDefault enableZoom={true} enableRotate={false} />
      )}
      <CameraFocus />
    </>
  );
};
