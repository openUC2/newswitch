import {
  useMoveState,
  type MoveValue,
} from "@/apps/default/hooks/states/MoveState";

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

export const useStage = (): Stage => {
  const { data } = useMoveState({ subscribe: true });
  return stageOf(entriesOf(data?.moves));
};

/** Where the view is: the sum of whatever moves it along each way. */
export const useStagePosition = () => {
  const stage = useStage();
  const sum = (moves: MoveValue[]) =>
    moves.reduce((total, move) => total + move.value, 0);
  return { x: sum(stage.x), y: sum(stage.y), z: sum(stage.focus) };
};
