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
import { ElementNode } from "./ElementNode";

const nodeTypes = { element: ElementNode };

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
    const initialNodes: Node[] = path.elements.map((element) => ({
      id: element.name,
      type: "element",
      position: { x: 0, y: 0 }, // Dagre overwrites this instantly
      data: element,
    }));

    const initialEdges: Edge[] = path.edges.map((e, index) => ({
      id: `edge-${e.source}-${e.target}-${index}`,
      source: e.source,
      target: e.target,
      label: e.via ?? e.side ?? undefined,
      animated: true,
      style: { stroke: "#555", strokeWidth: 2 },
    }));

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
