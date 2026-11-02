import { useDetectorState } from "@/apps/default/hooks/states";
import { deliversImages, useSeesScene } from "@/lib/microscope/space";
import { useMemo } from "react";
import { LivePlane } from "./stream/LivePlane";

const MAX_DISPLAYABLE = 10;

export const LivesPlane = () => {
  // 1. Get the descriptors directly from your backend state hook

  const { data: detectorState } = useDetectorState({ subscribe: true });
  const sees = useSeesScene();

  const renderableDetectors = useMemo(() => {
    // What measures at a point (a thermometer) has no image to place.
    // Of the scene's sample only: another sample's camera looks at another stage.
    return detectorState?.detectors
      ?.filter((d) => deliversImages(d) && sees(d.name))
      .slice(0, MAX_DISPLAYABLE);
  }, [detectorState?.detectors, sees]);

  if (!detectorState) return null;
  if (!detectorState.is_acquiring) return null; // Only show live planes if we're actively acquiring

  // 2. Map over them. React handles all mounting, fetching, and unmounting automatically.
  return (
    <group>
      {renderableDetectors?.map((detector) => (
        <LivePlane key={detector.name} detector={detector} />
      ))}
    </group>
  );
};
