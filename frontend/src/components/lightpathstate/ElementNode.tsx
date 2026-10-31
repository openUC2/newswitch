import type { LightElement } from "@/apps/default/hooks/states/OpticsState";
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import React from "react";

type ElementNodeProps = NodeProps<Node<LightElement>>;

/** One element on a light path, whatever it is: what it is made of, and what it is set to. */
export const ElementNode: React.FC<ElementNodeProps> = ({ data }) => (
  <div className="rounded-md border bg-card px-3 py-2 text-[10px] text-card-foreground">
    <Handle type="target" position={Position.Left} />
    <div className="text-xs font-semibold">{data.label}</div>
    <div className="mb-1 text-muted-foreground">{data.kind}</div>
    {Object.entries({ ...data.facts, ...data.values }).map(([label, value]) => (
      <div key={label} className="flex justify-between gap-3">
        <span className="text-muted-foreground">
          {label.replaceAll("_", " ")}
        </span>
        <span>{value}</span>
      </div>
    ))}
    <Handle type="source" position={Position.Right} />
  </div>
);
