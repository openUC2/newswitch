import { useExpanseState } from "@/apps/default/hooks/states/ExpanseState";
import { FrameVolume } from "./FrameVolume";
import { useMemo } from "react";
import { useSceneSample } from "@/lib/microscope/sampleContext";

const MAX_DISPLAYABLE = 10;

export const FramesPlane = () => {
  // 1. Get the descriptors directly from your backend state hook
  const { data: frames } = useExpanseState({
    selector: (state) => state.current_frames,
  });

  const sample = useSceneSample();
  // What was taken of the scene's sample: another sample's frames are placed in another frame.
  const renderedAbleFrames = useMemo(() => {
    return frames
      ?.filter(
        (frame) => !frame.metadata.sample || frame.metadata.sample === sample,
      )
      .slice(0, MAX_DISPLAYABLE);
  }, [frames, sample]);

  // 2. Map over them. React handles all mounting, fetching, and unmounting automatically.
  return (
    <group>
      {renderedAbleFrames?.map((frame) => (
        <FrameVolume key={frame.id} frame={frame} />
      ))}
    </group>
  );
};
