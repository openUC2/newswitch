import { useMoveTo } from "@/apps/default/hooks/actions";
import { useSpaceState } from "@/apps/default/hooks/states/SpaceState";
import { useModeStore } from "@/store/modeStore";
import { Line } from "@react-three/drei";

/** Below the images, above the stage's grid. */
const DEPTH = -0.5;

/**
 * What is mounted, on the sample: its outline from its top left corner, and a plate's wells.
 * In move mode (hold M) a click on a well brings its middle to the middle of the view.
 */
export const HolderPlane = () => {
  const { data } = useSpaceState({ subscribe: true });
  const { assign } = useMoveTo();
  const interactionMode = useModeStore((s) => s.interactionMode);
  const shape = data?.shape;
  if (!shape) return null;

  const { width_um: width, height_um: height } = shape;
  return (
    <group>
      <Line
        points={[
          [0, 0, DEPTH],
          [width, 0, DEPTH],
          [width, height, DEPTH],
          [0, height, DEPTH],
          [0, 0, DEPTH],
        ]}
        color="#64748b"
        lineWidth={1.5}
      />
      {shape.wells.map((well) => {
        const radius = (well.diameter_um ?? well.size_um ?? 1000) / 2;
        return (
          <group key={well.name} position={[well.x, well.y, DEPTH]}>
            {/* All of the well is what a click hits, not only its rim */}
            <mesh
              onClick={(e) => {
                if (interactionMode !== "MOVE") return;
                e.stopPropagation();
                assign({
                  position: { system: well.name, coordinates: { x: 0, y: 0 } },
                });
              }}
            >
              {well.size_um ? (
                <planeGeometry args={[well.size_um, well.size_um]} />
              ) : (
                <circleGeometry args={[radius, 48]} />
              )}
              <meshBasicMaterial color="#94a3b8" transparent opacity={0.06} />
            </mesh>
            {!well.size_um && (
              <mesh>
                <ringGeometry args={[radius * 0.94, radius, 48]} />
                <meshBasicMaterial color="#94a3b8" transparent opacity={0.5} />
              </mesh>
            )}
          </group>
        );
      })}
    </group>
  );
};
