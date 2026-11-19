import {
  useMoveState,
  type MoveValue,
} from "@/apps/default/hooks/states/MoveState";
import { useOpticsState } from "@/apps/default/hooks/states/OpticsState";
import { useSpaceState } from "@/apps/default/hooks/states/SpaceState";
import { useSceneSample } from "./sampleContext";

/** Every entry of a state keyed by cube, then by variable. */
export const entriesOf = <T>(byCube?: Record<string, Record<string, T>>): T[] =>
  Object.values(byCube ?? {}).flatMap((byVariable) =>
    Object.values(byVariable),
  );

/** What moves the view, and what focuses it: found by the server, never by a name in here. */
export type Stage = {
  x: MoveValue[];
  y: MoveValue[];
  focus: MoveValue[];
  rest: MoveValue[];
};

export const stageOf = (moves: MoveValue[]): Stage => {
  const sideways = (along: string) =>
    moves.filter((m) => m.along === along && m.does.includes("position"));
  const x = sideways("x");
  const y = sideways("y");
  const focus = moves.filter(
    (m) => m.does.includes("blur") && !m.does.includes("scale"),
  );
  const found = new Set([...x, ...y, ...focus].map((m) => m.name));
  return { x, y, focus, rest: moves.filter((m) => !found.has(m.name)) };
};

/** What moves the scene's sample's view: every move but those of another sample's stage. */
export const useStage = (): Stage => {
  const { data } = useMoveState({ subscribe: true });
  const { data: space } = useSpaceState({ subscribe: true });
  const sample = useSceneSample();
  const others = new Set(
    Object.keys(space?.samples ?? {}).filter((cube) => cube !== sample),
  );
  const moves = Object.entries(data?.moves ?? {})
    .filter(([cube]) => !others.has(cube))
    .flatMap(([, byVariable]) => Object.values(byVariable));
  return stageOf(moves);
};

/** Where the scene's view is: the sum of whatever moves it along each way. */
export const useStagePosition = () => {
  const stage = useStage();
  const { data: optics } = useOpticsState({ subscribe: true });
  const { data: space } = useSpaceState({ subscribe: true });
  const sample = useSceneSample();
  const sum = (moves: MoveValue[]) =>
    moves.reduce((total, move) => total + move.current, 0);
  // Along the axis, the server says: which plane is seen depends on the sample and the light.
  const seeing = Object.values(space?.detectors ?? {}).find(
    (placed) => placed.sample === sample,
  )?.detector;
  const plane =
    seeing === undefined ? undefined : optics?.detectors?.[seeing]?.plane_um;
  return { x: sum(stage.x), y: sum(stage.y), z: plane ?? sum(stage.focus) };
};
