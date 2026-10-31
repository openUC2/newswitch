import dagre from "dagre";

/** What of a light path a layout needs: its cubes and how light connects them. */
export type PathGraph = {
  elements: readonly { name: string }[];
  edges: readonly { source: string; target: string }[];
};

/** How far apart elements are drawn, in the scene's units. */
const NODE_SIZE = 12;
const NODE_GAP = 14;
const RANK_GAP = 18;

/**
 * Where to draw each element: along the way light takes, whatever is on it.
 * Light runs along the scene's z, with branches side by side in x, around the scene's middle.
 */
export const layoutPath = (path: PathGraph) => {
  const graph = new dagre.graphlib.Graph();
  graph.setDefaultEdgeLabel(() => ({}));
  graph.setGraph({ rankdir: "TB", nodesep: NODE_GAP, ranksep: RANK_GAP });
  for (const element of path.elements) {
    graph.setNode(element.name, { width: NODE_SIZE, height: NODE_SIZE });
  }
  for (const edge of path.edges) {
    graph.setEdge(edge.source, edge.target);
  }
  dagre.layout(graph);

  const { width = 0, height = 0 } = graph.graph();
  return new Map<string, [number, number, number]>(
    path.elements.map((element) => {
      const { x, y } = graph.node(element.name);
      return [element.name, [x - width / 2, 0, height / 2 - y]];
    }),
  );
};
