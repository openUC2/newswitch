import { useMoveTo } from "@/apps/default/hooks/actions";
import { Html, Line } from "@react-three/drei";
import { useState } from "react";
import type { Vector3 } from "three";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useLookingAt } from "@/lib/microscope/space";

/**
 * Brings a point of the sample (the scene's frame) to the middle of the view, in x and y only: a
 * click on the scene says nothing about focus. The server finds what to move (`move_to`).
 */
const useMoveViewTo = () => {
  const { assign } = useMoveTo();
  return (x: number, y: number) => {
    assign({ position: { system: "sample", coordinates: { x, y } } });
  };
};
import { useModeStore } from "@/store/modeStore";

/**
 * Crosshair (Fadenkreuz) Component
 * Renders at the clicked world coordinates.
 */
const SelectionCrosshair = ({ position }: { position: Vector3 }) => {
  const size = 10; // The length of the crosshair arms in µm

  return (
    <group position={position}>
      {/* Horizontal Line */}
      <Line
        points={[
          [-size, 0, 0.1],
          [size, 0, 0.1],
        ]}
        color="#10b981" // Emerald
        lineWidth={1.5}
      />
      {/* Vertical Line */}
      <Line
        points={[
          [0, -size, 0.1],
          [0, size, 0.1],
        ]}
        color="#10b981"
        lineWidth={1.5}
      />
      {/* Outer Glow / Halo */}
      <mesh position={[0, 0, 0.05]}>
        <ringGeometry args={[size * 0.8, size, 32]} />
        <meshBasicMaterial color="#10b981" transparent opacity={0.2} />
      </mesh>
    </group>
  );
};

/**
 * ClickWidget: Context menu for world-space interaction.
 *
 * TODO: not wired up - StagePositioner only renders the SelectionCrosshair for the
 * current clickPoint; this context menu is never mounted. Exported so the unfinished
 * wiring is preserved rather than deleted.
 */
export const ClickWidget = ({
  position,
  onClose,
}: {
  position: Vector3;
  onClose: () => void;
}) => {
  const moveTo = useMoveViewTo();

  return (
    <Html position={position} center distanceFactor={1}>
      <Card className="min-w-[150px] p-3 bg-gray-800/90 border-gray-700">
        <div className="flex items-center justify-between gap-4">
          <span className="text-[10px] font-bold uppercase tracking-widest text-emerald-400">
            Targeting
          </span>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-white text-xs"
          >
            ✕
          </button>
        </div>
        {position && (
          <div className="mt-2 text-xs font-mono bg-gray-700/50 p-2 rounded">
            X: {position.x.toFixed(2)}
            <br />
            Y: {position.y.toFixed(2)}
            <br />
            Z: {position.z.toFixed(2)}
          </div>
        )}
        <Button
          onClick={() => {
            moveTo(position.x, position.y);
            onClose();
          }}
          className="w-full mt-2 text-xs bg-emerald-600 hover:bg-emerald-700 text-white py-1 px-2 rounded"
        >
          Move Here
        </Button>
      </Card>
    </Html>
  );
};

/**
 * StagePositioner
 * An invisible plane that covers the scene to catch targeting clicks.
 * Decouples interaction from the visual stage mesh.
 */
export const StagePositioner = () => {
  const interactionMode = useModeStore((s) => s.interactionMode);
  const [clickPoint, setClickPoint] = useState<Vector3 | null>(null);
  const moveTo = useMoveViewTo();
  const lookingAt = useLookingAt();

  if (interactionMode !== "MOVE") return null;

  return (
    <group>
      {/* Invisible Catch-All Plane for Pointer Events */}
      <mesh
        // Below the stage and its grid, around where the view is
        position={[lookingAt?.x ?? 0, lookingAt?.y ?? 0, -2]}
        onClick={async (e) => {
          e.stopPropagation();
          setClickPoint(e.point);
          moveTo(e.point.x, e.point.y);
        }}
      >
        {/* Wider than any holder, so that anywhere on the sample can be clicked */}
        <planeGeometry args={[300000, 300000]} />
        <meshBasicMaterial visible={false} />
      </mesh>

      {/* Render the targeting UI if a point is selected */}
      {clickPoint && (
        <>
          <SelectionCrosshair position={clickPoint} />
        </>
      )}
    </group>
  );
};
