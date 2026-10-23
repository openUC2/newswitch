import React, { useEffect } from "react";
import {
  ReactFlow,
  Background,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { type z } from "zod";

import type { LightPathSnapshotSchema } from "@/apps/default/hooks/states/ExpanseState";
import { getLayoutedElements } from "./layoutUtils";
import { nodeTypes } from "./nodes";

export type LightPathSnapshot = z.infer<typeof LightPathSnapshotSchema>;

interface OpticalPathViewerProps {
  path: LightPathSnapshot;
}

export const LightPathStateRender: React.FC<OpticalPathViewerProps> = ({
  path,
}) => {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  useEffect(() => {
    const kubes = path.kubes;
    const rawEdges = path.edges;

    // 1. Create initial React Flow Nodes, keyed by the kube's runtime discriminant.
    // This was `kube.__brand`, which is a zod brand: type-level only, undefined at
    // runtime - so every node got type undefined and React Flow fell back to its
    // default renderer instead of the custom nodes in ./nodes. The nodeTypes keys
    // (objective_kube_state, detector_kube_state, ...) are exactly the __identifier values.
    const initialNodes: Node[] = kubes.map((kube) => ({
      id: kube.kube_id,
      type: kube.__identifier,
      position: { x: 0, y: 0 }, // Dagre overwrites this instantly
      data: kube,
    }));

    // 2. Create initial React Flow Edges
    const initialEdges: Edge[] = rawEdges.map((e, index) => ({
      id: `edge-${e.source}-${e.target}-${index}`,
      source: e.source,
      target: e.target,
      label: e.polarization
        ? `Pol: ${e.polarization}`
        : e.intensity !== null
          ? `${e.intensity}%`
          : undefined,
      animated: true,
      style: { stroke: "#555", strokeWidth: 2 },
    }));

    // 3. Apply Dagre Layout
    const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
      initialNodes,
      initialEdges,
      "LR",
    );

    setNodes(layoutedNodes);
    setEdges(layoutedEdges);
  }, [path, setNodes, setEdges]);

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
      }}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        proOptions={{
          hideAttribution: true,
        }}
      >
        <Background gap={16} size={1} />
      </ReactFlow>
    </div>
  );
};
