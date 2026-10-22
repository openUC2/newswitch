import { useLightPathState } from "@/apps/default/hooks/states";

export const LightPaths = () => {
  const { data } = useLightPathState({ subscribe: true });

  return (
    <div className="flex justify-center">
      {data?.light_paths?.map((value) => (
        <div key={value.detector} className="border p-2 m-2">
          <h3 className="font-bold">Light Path: detector {value.detector}</h3>
          <p>Kubes:</p>
          <ul className="list-disc list-inside">
            {value.kubes.map((kube, index) => (
              <li key={index}>
                {/* __identifier is the runtime discriminant. `__brand` is a zod brand:
                    type-level only, undefined at runtime - so comparing against it was
                    always false and every kube rendered as a detector kube. */}
                {kube.__identifier === "@newswitch/objective_kube"
                  ? `Objective Kube: ${kube.kube_id}`
                  : `Detector Kube: ${kube.kube_id}`}
              </li>
            ))}
          </ul>
          <p>Edges:</p>
          <ul className="list-disc list-inside">
            {value.edges.map((edge, index) => (
              <li key={index}>
                {edge.source} → {edge.target} (Intensity:{" "}
                {edge.intensity !== null ? edge.intensity : "N/A"})
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
};
