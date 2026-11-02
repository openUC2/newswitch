import { useMeasuredPoints } from "@/lib/microscope/space";
import { Html } from "@react-three/drei";

/** Above the holder, below the images. */
const DEPTH = -0.25;
/** How large the mark is, in sample micrometres: seen from afar, as such a thing is. */
const RADIUS = 600;

/**
 * Where each detector that measures at one point measures (a thermometer beside the sample),
 * placed by the server (`SpaceState.points`), with what it read last.
 */
export const PointsPlane = () => {
  const points = useMeasuredPoints();
  return (
    <group>
      {points.map((point) => (
        <group key={point.detector} position={[point.x, point.y, DEPTH]}>
          <mesh>
            <circleGeometry args={[RADIUS, 32]} />
            <meshBasicMaterial color="#f59e0b" transparent opacity={0.35} />
          </mesh>
          <mesh>
            <ringGeometry args={[RADIUS * 0.85, RADIUS, 32]} />
            <meshBasicMaterial color="#f59e0b" />
          </mesh>
          <Html center position={[0, -RADIUS * 1.8, 0]} zIndexRange={[10, 0]}>
            <div className="pointer-events-none whitespace-nowrap rounded bg-black/70 px-1.5 py-0.5 font-mono text-[10px] text-amber-300">
              {point.detector}{" "}
              {point.reading === null
                ? "…"
                : `${point.reading.toFixed(2)} ${point.unit}`}
            </div>
          </Html>
        </group>
      ))}
    </group>
  );
};
