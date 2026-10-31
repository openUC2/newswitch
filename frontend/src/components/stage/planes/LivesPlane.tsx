import { useDetectorState } from "@/apps/default/hooks/states";
import { useMemo } from "react";
import { LivePlane } from "./stream/LivePlane";

const MAX_DISPLAYABLE = 10;

export const LivesPlane = () => {
  // 1. Get the descriptors directly from your backend state hook

  const { data: detectorState } = useDetectorState({ subscribe: true });

  const renderableDetectors = useMemo(() => {
    return detectorState?.detectors?.map((x) => x).slice(0, MAX_DISPLAYABLE);
  }, [detectorState?.detectors]);

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
