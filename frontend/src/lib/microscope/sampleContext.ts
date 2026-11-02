import { useSpaceState } from "@/apps/default/hooks/states/SpaceState";
import { useModeStore } from "@/store/modeStore";
import { createContext, useContext } from "react";

/**
 * Which sample the stage view is of. A microscope may have several, each on a stage of its own
 * (`SpaceState.samples`, by the cube holding it): the view shows one, its frames, its live images,
 * its holder and its stage, and what moves it (`useStage`) is that one's. A view can pin it
 * (`StageView sample=...`, `SceneSampleContext`); otherwise it is the one picked (`SamplePicker`,
 * kept in the page's mode store, so the panels beside the scene follow it too), or else the first.
 */
export const SceneSampleContext = createContext<string | undefined>(undefined);

/** The samples there are, by the cubes holding them. */
export const useSamples = (): string[] => {
  const { data } = useSpaceState({ subscribe: true });
  return Object.keys(data?.samples ?? {});
};

/** The sample the view is of: the one pinned around, else the one picked, else the first. */
export const useSceneSample = (): string | undefined => {
  const pinned = useContext(SceneSampleContext);
  const picked = useModeStore((s) => s.sceneSample);
  const samples = useSamples();
  if (pinned !== undefined) return pinned;
  if (picked !== null && samples.includes(picked)) return picked;
  return samples[0];
};
