import { useLookingAt, useViewField } from "@/lib/microscope/space";
import { useModeStore } from "@/store/modeStore";
import { useScansStore, type ScanRegion } from "@/store/scansStore";
import { Line } from "@react-three/drei";
import { useMemo, useState } from "react";
import * as THREE from "three";

// --- Path Generation Component ---

const ScanPathPreview = ({ region }: { region: ScanRegion }) => {
  // What the view's detector sees, on the sample: as the server tiles a region with it.
  const field = useViewField();

  const { pathPoints, fovWidth, fovHeight } = useMemo(() => {
    if (!field) return { pathPoints: [], fovWidth: 0, fovHeight: 0 };

    const calculatedFovWidth = field.width;
    const calculatedFovHeight = field.height;

    if (calculatedFovWidth === 0 || calculatedFovHeight === 0) {
      return { pathPoints: [], fovWidth: 0, fovHeight: 0 };
    }

    const minX = Math.min(region.start.x, region.end.x);
    const maxX = Math.max(region.start.x, region.end.x);
    const minY = Math.min(region.start.y, region.end.y);
    const maxY = Math.max(region.start.y, region.end.y);

    const safeOverlap = Math.min(region.overlap, 99) / 100;
    const stepX = calculatedFovWidth * (1 - safeOverlap);
    const stepY = calculatedFovHeight * (1 - safeOverlap);

    // Calculate how many columns and rows are needed to cover the drawn area
    const cols = Math.max(
      1,
      Math.ceil((maxX - minX - calculatedFovWidth) / stepX) + 1,
    );
    const rows = Math.max(
      1,
      Math.ceil((maxY - minY - calculatedFovHeight) / stepY) + 1,
    );

    // Center of the user-drawn region
    const regionCenterX = (minX + maxX) / 2;
    const regionCenterY = (minY + maxY) / 2;

    // Total physical dimensions of the resulting grid
    const totalGridWidth = (cols - 1) * stepX + calculatedFovWidth;
    const totalGridHeight = (rows - 1) * stepY + calculatedFovHeight;

    // Shift the starting point so the grid is perfectly centered over the drawn region
    const startX = regionCenterX - totalGridWidth / 2 + calculatedFovWidth / 2;
    const startY =
      regionCenterY - totalGridHeight / 2 + calculatedFovHeight / 2;

    const points: [number, number, number][] = [];

    if (region.pattern === "SNAKE_ROW" || region.pattern === "RASTER_ROW") {
      for (let r = 0; r < rows; r++) {
        const y = startY + r * stepY;
        const isReverse = region.pattern === "SNAKE_ROW" && r % 2 !== 0;

        for (let c = 0; c < cols; c++) {
          const actualC = isReverse ? cols - 1 - c : c;
          const x = startX + actualC * stepX;
          points.push([x, y, 0.15]);
        }
      }
    } else {
      for (let c = 0; c < cols; c++) {
        const x = startX + c * stepX;
        const isReverse = region.pattern === "SNAKE_COL" && c % 2 !== 0;

        for (let r = 0; r < rows; r++) {
          const actualR = isReverse ? rows - 1 - r : r;
          const y = startY + actualR * stepY;
          points.push([x, y, 0.15]);
        }
      }
    }

    return {
      pathPoints: points,
      fovWidth: calculatedFovWidth,
      fovHeight: calculatedFovHeight,
    };
  }, [region, field]);

  if (pathPoints.length === 0) return null;

  const w2 = fovWidth / 2;
  const h2 = fovHeight / 2;

  return (
    <group>
      {pathPoints.map((pt, i) => {
        const cx = pt[0];
        const cy = pt[1];
        return (
          <Line
            key={`fov-${i}`}
            points={[
              [cx - w2, cy - h2, 0.12],
              [cx + w2, cy - h2, 0.12],
              [cx + w2, cy + h2, 0.12],
              [cx - w2, cy + h2, 0.12],
              [cx - w2, cy - h2, 0.12],
            ]}
            color="var(--slate-500)"
            lineWidth={1}
            opacity={0.4}
            transparent
          />
        );
      })}

      <Line
        points={pathPoints}
        color="hsl(57, 71%, 80%)"
        lineWidth={1.5}
        opacity={0.7}
      />

      {pathPoints.map((pt, i) => (
        <mesh key={`marker-${i}`} position={[pt[0], pt[1], pt[2] + 0.01]}>
          <circleGeometry
            args={[Math.max(0.5, pathPoints.length > 100 ? 0.2 : 1), 16]}
          />
          <meshBasicMaterial color="#fafafa" />
        </mesh>
      ))}
    </group>
  );
};

export const RectangleDrawer = () => {
  // Mode store state
  const interactionMode = useModeStore((s) => s.interactionMode);

  // Scans store global state
  const regions = useScansStore((s) => s.regions);
  const selectedRegionId = useScansStore((s) => s.selectedRegionId);
  const addRegion = useScansStore((s) => s.addRegion);
  const setSelectedRegionId = useScansStore((s) => s.setSelectedRegionId);

  // Local transient state for the drawing interaction only
  const [startPos, setStartPos] = useState<THREE.Vector3 | null>(null);
  const [currentPos, setCurrentPos] = useState<THREE.Vector3 | null>(null);
  const lookingAt = useLookingAt();

  if (interactionMode !== "SCAN") return null;

  return (
    <group>
      <mesh
        position={[lookingAt?.x ?? 0, lookingAt?.y ?? 0, 0]}
        onClick={(e) => {
          e.stopPropagation();
          setSelectedRegionId(null);
        }}
        onPointerDown={(e) => {
          if (!e.ctrlKey && !e.metaKey) return;
          e.stopPropagation();
          setStartPos(e.point);
          setSelectedRegionId(null);
        }}
        onPointerMove={(e) => {
          if (startPos) {
            e.stopPropagation();
            setCurrentPos(e.point);
          }
        }}
        onPointerUp={(e) => {
          if (startPos && currentPos) {
            e.stopPropagation();
            const newId = Math.random().toString(36).substring(2, 9);

            addRegion({
              id: newId,
              start: startPos,
              end: currentPos,
              pattern: "SNAKE_ROW",
              overlap: 10,
            });

            setSelectedRegionId(newId);
          }
          setStartPos(null);
          setCurrentPos(null);
        }}
      >
        <planeGeometry args={[300000, 300000]} />
        <meshBasicMaterial visible={false} />
      </mesh>

      {regions.map((region) => {
        const isSelected = selectedRegionId === region.id;

        const width = Math.abs(region.end.x - region.start.x);
        const height = Math.abs(region.end.y - region.start.y);
        const centerX = (region.start.x + region.end.x) / 2;
        const centerY = (region.start.y + region.end.y) / 2;

        return (
          <group key={region.id}>
            <mesh
              position={[centerX, centerY, 0.05]}
              onClick={(e) => {
                if (e.ctrlKey || e.metaKey) return;
                e.stopPropagation();
                setSelectedRegionId(region.id);
              }}
            >
              <planeGeometry args={[width, height]} />
              <meshBasicMaterial
                color={isSelected ? "#fafafa" : "#a1a1aa"}
                transparent
                opacity={isSelected ? 0.1 : 0.05}
                side={THREE.DoubleSide}
              />
            </mesh>

            <Line
              points={[
                [region.start.x, region.start.y, 0.1],
                [region.end.x, region.start.y, 0.1],
                [region.end.x, region.end.y, 0.1],
                [region.start.x, region.end.y, 0.1],
                [region.start.x, region.start.y, 0.1],
              ]}
              color={isSelected ? "#fafafa" : "#52525b"}
              lineWidth={isSelected ? 3 : 2}
            />

            {isSelected && <ScanPathPreview region={region} />}
          </group>
        );
      })}

      {startPos && currentPos && (
        <Line
          points={[
            [startPos.x, startPos.y, 0.1],
            [currentPos.x, startPos.y, 0.1],
            [currentPos.x, currentPos.y, 0.1],
            [startPos.x, currentPos.y, 0.1],
            [startPos.x, startPos.y, 0.1],
          ]}
          color="#fafafa"
          lineWidth={2}
        />
      )}
    </group>
  );
};
