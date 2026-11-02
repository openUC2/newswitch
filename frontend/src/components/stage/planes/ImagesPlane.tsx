import { Suspense } from "react";
import ImagePlane from "./ImagePlane";
import { useExpanseState } from "@/apps/default/hooks/states/ExpanseState";
import { useSceneSample } from "@/lib/microscope/sampleContext";

export const ImagesPlane = () => {
  const { data: expanseState } = useExpanseState({ subscribe: true });
  const sample = useSceneSample();

  return (
    <Suspense fallback={<></>}>
      {expanseState?.current_images
        ?.filter(
          (img) => !img.metadata.sample || img.metadata.sample === sample,
        )
        .map((img, idx) => (
          <ImagePlane key={img.id} image={img} index={idx} />
        ))}
    </Suspense>
  );
};
