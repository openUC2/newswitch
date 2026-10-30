import { frameToRgba, type LiveFrame } from "@/components/liveview/frames";
import {
  DEFAULT_MAX_SIZE,
  useFrameStream,
} from "@/components/liveview/frameStream";
import { useFrame } from "@react-three/fiber";
import { useEffect, useRef, useState } from "react";
import {
  DataTexture,
  LinearFilter,
  RGBAFormat,
  SRGBColorSpace,
  UnsignedByteType,
} from "three";

/** A texture of a detector's newest frame, null until the first one came. */
export const useLiveFrameTexture = (slot: number) => {
  const latestRef = useRef<LiveFrame | null>(null);
  const shownRef = useRef<LiveFrame | null>(null);
  // Written from useFrame: held in a ref, the state only tells React it was replaced.
  const textureRef = useRef<DataTexture | null>(null);
  const [texture, setTexture] = useState<DataTexture | null>(null);

  useFrameStream(slot, DEFAULT_MAX_SIZE, (frame) => {
    latestRef.current = frame;
  });

  useFrame(() => {
    const frame = latestRef.current;
    if (!frame || frame === shownRef.current) return;
    shownRef.current = frame;

    const current = textureRef.current;
    if (
      current &&
      current.image.width === frame.width &&
      current.image.height === frame.height
    ) {
      current.image.data = frameToRgba(frame);
      current.needsUpdate = true;
      return;
    }

    const next = new DataTexture(
      frameToRgba(frame),
      frame.width,
      frame.height,
      RGBAFormat,
      UnsignedByteType,
    );
    next.colorSpace = SRGBColorSpace;
    next.magFilter = LinearFilter;
    next.minFilter = LinearFilter;
    next.flipY = true; // the frame's first row is the image's top
    next.needsUpdate = true;
    current?.dispose();
    textureRef.current = next;
    setTexture(next);
  });

  useEffect(
    () => () => {
      textureRef.current?.dispose();
      textureRef.current = null;
    },
    [],
  );

  return texture;
};
