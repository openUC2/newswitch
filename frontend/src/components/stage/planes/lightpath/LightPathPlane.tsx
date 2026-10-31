import {
  useOpticsState,
  type LightElement,
} from "@/apps/default/hooks/states/OpticsState";
import { useElementStore } from "@/store/elementStore";
import { useModeStore } from "@/store/modeStore";
import { Html, Line } from "@react-three/drei";
import { useMemo } from "react";
import * as THREE from "three";
import { useSelectedFrame } from "../../hooks/useSelectedFrame";
import { layoutPath, type PathGraph } from "./layout";

const SIZE = 10;
const BOX = new THREE.BoxGeometry(SIZE, SIZE / 3, SIZE / 2);

const ElementBox = ({
  element,
  position,
}: {
  element: LightElement;
  position: [number, number, number];
}) => {
  const selected = useElementStore(
    (s) => s.selectedElement?.name === element.name,
  );
  const setSelected = useElementStore((s) => s.setSelectedElement);

  return (
    <group
      position={position}
      name={element.name}
      onClick={(event) => {
        event.stopPropagation();
        setSelected(selected ? null : element);
      }}
    >
      <mesh geometry={BOX}>
        <meshBasicMaterial color={selected ? "#0ea5e9" : "#94a3b8"} />
      </mesh>
      {selected && (
        <mesh geometry={BOX} scale={1.08}>
          <meshBasicMaterial color="#10b981" side={THREE.BackSide} />
        </mesh>
      )}
      <Html
        position={[SIZE * 0.7, 0, 0]}
        style={{ transform: "translateY(-50%)" }}
      >
        <div className="pointer-events-none whitespace-nowrap text-center text-[11px] text-slate-200">
          {element.label}
          <div className="text-[9px] text-slate-400">{element.kind}</div>
        </div>
      </Html>
    </group>
  );
};

/** A light path, as it is described: every element on it, and the way light takes between them. */
export const LightPathPlane = ({
  path,
}: {
  path: { elements: readonly LightElement[]; edges: PathGraph["edges"] };
}) => {
  const where = useMemo(() => layoutPath(path), [path]);

  return (
    <>
      {path.edges.map((edge) => {
        const from = where.get(edge.source);
        const to = where.get(edge.target);
        return from && to ? (
          <Line
            key={`${edge.source}-${edge.target}`}
            points={[from, to]}
            color="#38bdf8"
            lineWidth={1.5}
          />
        ) : null;
      })}
      {path.elements.map((element) => (
        <ElementBox
          key={element.name}
          element={element}
          position={where.get(element.name) ?? [0, 0, 0]}
        />
      ))}
    </>
  );
};

/** The light path of the first detector, as things are now. */
export const CurrentLightPathPlane = () => {
  const { data } = useOpticsState({ subscribe: true });
  const currentMode = useModeStore((s) => s.interactionMode);
  const displayMode = useModeStore((s) => s.displayMode);
  const path = Object.values(data?.detectors ?? {}).at(0)?.path;

  if (currentMode !== "META" || displayMode !== "3D" || !path) return null;
  return <LightPathPlane path={path} />;
};

/** The light path the selected frame was taken with. */
export const CurrentFrameLightPathPlane = () => {
  const frame = useSelectedFrame();
  const displayMode = useModeStore((s) => s.displayMode);
  const path = frame?.metadata?.light_state;

  if (displayMode !== "3D" || !path) return null;
  return <LightPathPlane path={path} />;
};
