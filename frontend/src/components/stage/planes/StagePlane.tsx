import { useMount } from "@/lib/microscope/space";
import { useStage, useStagePosition } from "@/lib/microscope/values";
import { useModeStore } from "@/store/modeStore";
import { useMemo } from "react";
import { Matrix4 } from "three";

/**
 * StagePlane
 * A purely visual representation of the stage's physical extent and position, on the sample:
 * where the stage is, through the mount (stage to sample).
 * Has no interactive event listeners.
 */
export const StagePlane = () => {
  const stageState = useStagePosition();
  const stage = useStage();
  const mount = useMount();
  const interactionMode = useModeStore((s) => s.interactionMode);
  const placed = useMemo(
    () =>
      mount
        .clone()
        .multiply(
          new Matrix4().makeTranslation(
            stageState.x,
            stageState.y,
            stageState.z,
          ),
        ),
    [mount, stageState.x, stageState.y, stageState.z],
  );

  if (!stageState) return null;
  if (interactionMode === "META") return null;

  const stageRangeX = Math.max(
    200,
    (stage.x[0]?.maximum ?? 100) - (stage.x[0]?.minimum ?? -100),
  );
  const stageRangeY = Math.max(
    200,
    (stage.y[0]?.maximum ?? 100) - (stage.y[0]?.minimum ?? -100),
  );

  const gridSize = Math.max(stageRangeX, stageRangeY);
  const divisions = 20;

  return (
    <group matrix={placed} matrixAutoUpdate={false}>
      {/* 1. The Solid Base */}
      <mesh position={[0, 0, -1]}>
        <planeGeometry args={[stageRangeX, stageRangeY]} />
        <meshStandardMaterial color="#ffffff" transparent opacity={0.2} />
      </mesh>

      {/* 2. The Functional Grid Overlay */}
      <gridHelper
        args={[gridSize, divisions, "#475569", "#1e293b"]}
        rotation={[Math.PI / 2, 0, 0]}
        position={[0, 0, -0.95]}
      />

      {/* 3. The Wireframe Boundary */}
      <mesh position={[0, 0, -0.9]}>
        <planeGeometry args={[stageRangeX, stageRangeY]} />
        <meshBasicMaterial color="#334155" wireframe wireframeLinewidth={5} />
      </mesh>
    </group>
  );
};
