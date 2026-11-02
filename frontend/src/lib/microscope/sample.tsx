import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
import { useModeStore } from "@/store/modeStore";
import { useContext, type ReactNode } from "react";
import {
  SceneSampleContext,
  useSamples,
  useSceneSample,
} from "./sampleContext";

/** Pins the sample the view inside is of; without `sample`, it is the one picked. */
export const SceneSampleProvider = ({
  sample,
  children,
}: {
  sample?: string;
  children: ReactNode;
}) => (
  <SceneSampleContext.Provider value={sample}>
    {children}
  </SceneSampleContext.Provider>
);

/** Switches which sample the view shows: only where there are several, and none is pinned. */
export const SamplePicker = () => {
  const pinned = useContext(SceneSampleContext);
  const samples = useSamples();
  const current = useSceneSample();
  const setSceneSample = useModeStore((s) => s.setSceneSample);
  if (pinned !== undefined || samples.length < 2) return null;
  return (
    <div className="absolute bottom-4 left-4 z-10 flex items-center gap-2">
      <span className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
        sample
      </span>
      <ButtonGroup>
        {samples.map((sample) => (
          <Button
            key={sample}
            size="xs"
            variant={sample === current ? "default" : "outline"}
            className={sample === current ? "" : "bg-black"}
            aria-pressed={sample === current}
            onClick={() => setSceneSample(sample)}
          >
            <span className="font-mono text-xs">{sample}</span>
          </Button>
        ))}
      </ButtonGroup>
    </div>
  );
};
