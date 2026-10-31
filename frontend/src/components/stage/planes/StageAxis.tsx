import { useStage } from "@/lib/microscope/values";
import { useModeStore } from "@/store/modeStore";
import { Line } from "@react-three/drei";

export const StageAxis = () => {
  const stage = useStage();
  const interactionMode = useModeStore((s) => s.interactionMode);

  if (interactionMode === "META") return null;

  const range = (moves: typeof stage.x) =>
    Math.max(200, (moves[0]?.maximum ?? 100) - (moves[0]?.minimum ?? -100));
  const stageRangeX = range(stage.x);
  const stageRangeY = range(stage.y);

  return (
    <group>
      <Line
        points={[
          [-stageRangeX / 2, 0, 0.1],
          [stageRangeX / 2, 0, 0.1],
        ]}
        color="#ef4444"
        lineWidth={1}
      />
      <Line
        points={[
          [0, -stageRangeY / 2, 0.1],
          [0, stageRangeY / 2, 0.1],
        ]}
        color="#22c55e"
        lineWidth={1}
      />
    </group>
  );
};
