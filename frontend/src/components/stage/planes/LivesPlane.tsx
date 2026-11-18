import { useCameraState } from "@/apps/default/hooks/states";
import { useMemo } from "react";
import { LivePlane } from "./stream/LivePlane";

const MAX_DISPLAYABLE = 10;

export const LivesPlane = () => {
  // 1. Get the descriptors directly from your backend state hook

  const { data: cameraState } = useCameraState({ subscribe: true });

  // Only active detectors: every plane sits at the same place, so the empty plane of a
  // switched-off detector would cover the live image of an active one.
  const renderableDetectors = useMemo(() => {
    return cameraState?.detectors
      ?.filter((detector) => detector.is_active)
      .slice(0, MAX_DISPLAYABLE);
  }, [cameraState?.detectors]);

  if (!cameraState) return null;
  if (!cameraState.is_acquiring) return null; // Only show live planes if we're actively acquiring

  // 2. Map over them. React handles all mounting, fetching, and unmounting automatically.
  return (
    <group>
      {renderableDetectors?.map((detector) => (
        <LivePlane key={detector.slot} detector={detector} />
      ))}
    </group>
  );
};
