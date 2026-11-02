/**
 * Debug view of the coordinate graph the microscope runs on (`SpaceState`): its systems with their
 * axes, the transformations between them part by part, the mount, and where every detector
 * measures on the sample. Read-only, and shown as the server publishes it: nothing is computed
 * here but the layout.
 */

import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  useSpaceState,
  type CoordinateSystem,
  type Transformation,
  type DimensionPart,
} from "@/apps/default/hooks/states/SpaceState";
import { useDetectorState } from "@/apps/default/hooks/states/DetectorState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

/** Up to four significant figures, without trailing zeros. */
const fmt = (value: number): string => {
  if (value === 0) return "0";
  const abs = Math.abs(value);
  if (abs >= 1e5 || abs < 1e-3) return value.toExponential(2);
  return Number(value.toPrecision(4)).toString();
};

/** A list of a holder's many places, collapsed: they are one kind of system. */
const PLACE = /^well:/;
const groupOf = (name: string) => (PLACE.test(name) ? "well:*" : name);

/** Which column of the diagram a system sits in: what measures, the stage, the sample, places. */
const columnOf = (name: string): number => {
  if (name.startsWith("detector:")) return 0;
  if (name === "stage") return 1;
  if (name === "sample") return 2;
  return 3;
};

/** A part, in one line: ``(x, y) → (x, y) AFFINE``. */
const partLabel = (part: DimensionPart) =>
  `(${part.input_axes.join(", ")}) → (${part.output_axes.join(", ")})`;

const edgeLabel = (edge: Transformation) =>
  edge.kind === "BY_DIMENSION"
    ? edge.parts.map(partLabel).join(" · ")
    : edge.kind.toLowerCase();

const Matrix = ({
  rows,
  columns,
  outputs,
}: {
  rows: number[][];
  columns: string[];
  outputs: string[];
}) => (
  <table className="font-mono text-[11px]">
    <thead>
      <tr className="text-muted-foreground">
        <th />
        {columns.map((name) => (
          <th key={name} className="px-1.5 text-right font-normal">
            {name}
          </th>
        ))}
        <th className="px-1.5 text-right font-normal">+</th>
      </tr>
    </thead>
    <tbody>
      {rows.map((row, index) => (
        <tr key={index}>
          <td className="pr-2 text-muted-foreground">{outputs[index]} =</td>
          {row.map((value, column) => (
            <td
              key={column}
              className={
                value === 0
                  ? "px-1.5 text-right text-muted-foreground/50"
                  : "px-1.5 text-right"
              }
            >
              {fmt(value)}
            </td>
          ))}
        </tr>
      ))}
    </tbody>
  </table>
);

const axesOf = (systems: CoordinateSystem[], name: string) =>
  systems.find((system) => system.name === name)?.axes.map((a) => a.name) ?? [];

/** The graph: systems as nodes in columns, transformations as arrows from input to output. */
const GraphDiagram = ({
  systems,
  edges,
}: {
  systems: CoordinateSystem[];
  edges: Transformation[];
}) => {
  const nodes = [...new Set(systems.map((system) => groupOf(system.name)))];
  const counts = new Map<string, number>();
  systems.forEach((system) => {
    const group = groupOf(system.name);
    counts.set(group, (counts.get(group) ?? 0) + 1);
  });
  // The columns there are, spread over the width: room between them for what the arrows say.
  const columns = [0, 1, 2, 3]
    .map((column) => nodes.filter((node) => columnOf(node) === column))
    .filter((column) => column.length > 0);
  const width = 1100;
  const margin = 100;
  const rowHeight = 96;
  const height = Math.max(...columns.map((c) => c.length), 1) * rowHeight + 40;
  const spacing =
    columns.length > 1 ? (width - 2 * margin) / (columns.length - 1) : 0;
  const place = new Map<string, { x: number; y: number }>();
  columns.forEach((column, index) => {
    const top = (height - column.length * rowHeight) / 2 + rowHeight / 2;
    column.forEach((node, row) =>
      place.set(node, {
        x: margin + index * spacing,
        y: top + row * rowHeight,
      }),
    );
  });
  const arrows = new Map<string, Transformation>();
  edges.forEach((edge) => {
    const key = `${groupOf(edge.input)}→${groupOf(edge.output)}`;
    if (!arrows.has(key)) arrows.set(key, edge);
  });

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full"
      role="img"
      aria-label="The coordinate graph"
    >
      <defs>
        <marker
          id="arrow"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M0,0 L10,5 L0,10 z" className="fill-muted-foreground" />
        </marker>
      </defs>
      {[...arrows.entries()].map(([key, edge]) => {
        const from = place.get(groupOf(edge.input));
        const to = place.get(groupOf(edge.output));
        if (!from || !to) return null;
        const direction = Math.sign(to.x - from.x) || 1;
        const x1 = from.x + direction * 82;
        const x2 = to.x - direction * 82;
        // Nearer where it starts: arrows that meet at one system keep their words apart.
        const along = 0.4;
        const middle = {
          x: x1 + (x2 - x1) * along,
          y: from.y + (to.y - from.y) * along,
        };
        return (
          <g key={key}>
            <line
              x1={x1}
              y1={from.y}
              x2={x2}
              y2={to.y}
              className="stroke-muted-foreground"
              strokeWidth={1.25}
              markerEnd="url(#arrow)"
            />
            <text
              x={middle.x}
              y={middle.y - 7}
              textAnchor="middle"
              className="fill-muted-foreground stroke-card font-mono"
              strokeWidth={4}
              paintOrder="stroke"
              fontSize={10}
            >
              {edgeLabel(edge)}
            </text>
            <text
              x={middle.x}
              y={middle.y + 13}
              textAnchor="middle"
              className="fill-muted-foreground/70 stroke-card"
              strokeWidth={4}
              paintOrder="stroke"
              fontSize={9}
            >
              {edge.kind}
              {edge.name ? ` · ${edge.name}` : ""}
            </text>
          </g>
        );
      })}
      {nodes.map((node) => {
        const at = place.get(node);
        if (!at) return null;
        const hub = node === "sample";
        const axes =
          node === "well:*"
            ? `${counts.get(node)} places · x, y`
            : axesOf(systems, node).join(", ") || "a point: no axes";
        return (
          <g key={node}>
            <rect
              x={at.x - 80}
              y={at.y - 22}
              width={160}
              height={44}
              rx={10}
              className={
                hub
                  ? "fill-primary/15 stroke-primary"
                  : "fill-card stroke-border"
              }
              strokeWidth={hub ? 1.5 : 1}
            />
            <text
              x={at.x}
              y={at.y - 3}
              textAnchor="middle"
              className="fill-foreground font-medium"
              fontSize={12}
            >
              {node}
            </text>
            <text
              x={at.x}
              y={at.y + 13}
              textAnchor="middle"
              className="fill-muted-foreground font-mono"
              fontSize={10}
            >
              {axes}
            </text>
          </g>
        );
      })}
    </svg>
  );
};

const TransformationCard = ({
  edge,
  systems,
}: {
  edge: Transformation;
  systems: CoordinateSystem[];
}) => (
  <div className="space-y-2 rounded-lg border p-3">
    <div className="flex flex-wrap items-center gap-2">
      <span className="font-mono text-sm">
        {edge.input} → {edge.output}
      </span>
      <Badge variant="secondary">{edge.kind}</Badge>
      {edge.name && <Badge variant="outline">{edge.name}</Badge>}
    </div>
    {edge.kind === "BY_DIMENSION" ? (
      <div className="space-y-2">
        {edge.parts.map((part, index) => (
          <div key={index} className="space-y-1 pl-3">
            <div className="flex items-center gap-2 text-xs">
              <Badge variant="outline">{part.kind}</Badge>
              <span className="font-mono">{partLabel(part)}</span>
            </div>
            {part.affine && (
              <Matrix
                rows={part.affine}
                columns={part.input_axes}
                outputs={part.output_axes}
              />
            )}
            {part.translation && (
              <span className="font-mono text-[11px]">
                + [{part.translation.map(fmt).join(", ")}]
              </span>
            )}
            {part.scale && (
              <span className="font-mono text-[11px]">
                × [{part.scale.map(fmt).join(", ")}]
              </span>
            )}
          </div>
        ))}
        {(() => {
          const named = new Set(edge.parts.flatMap((part) => part.input_axes));
          const unsaid = axesOf(systems, edge.input).filter(
            (axis) => !named.has(axis),
          );
          return unsaid.length > 0 ? (
            <p className="pl-3 text-xs text-muted-foreground">
              Placed nowhere: {unsaid.join(", ")}
            </p>
          ) : null;
        })()}
      </div>
    ) : (
      edge.affine && (
        <Matrix
          rows={edge.affine}
          columns={axesOf(systems, edge.input)}
          outputs={axesOf(systems, edge.output)}
        />
      )
    )}
  </div>
);

export function SpaceDebugPage() {
  const { t } = useTranslation();
  const { data: space } = useSpaceState({ subscribe: true });
  const { data: detectorState } = useDetectorState({ subscribe: true });
  const systems = space?.systems ?? [];
  const edges = space?.transformations ?? [];
  const placeEdges = edges.filter((edge) => PLACE.test(edge.input));
  const otherEdges = edges.filter((edge) => !PLACE.test(edge.input));
  const readings = new Map(
    (detectorState?.detectors ?? []).map((detector) => [
      detector.name,
      detector,
    ]),
  );

  return (
    <div className="h-full overflow-auto bg-background p-6 text-foreground">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 pb-24">
        <Button variant="ghost" size="sm" className="w-fit" asChild>
          <Link to="/">
            <ArrowLeft className="h-4 w-4" />
            {t("navigation.backToMicroscope")}
          </Link>
        </Button>

        <Card>
          <CardHeader>
            <CardTitle>Coordinate systems</CardTitle>
            <CardDescription>
              The graph the microscope places everything by, as the server
              publishes it (SpaceState). The sample is the hub; an image taken
              is placed by its frame's own matrix, not listed here.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {space ? (
              <GraphDiagram systems={systems} edges={edges} />
            ) : (
              <p className="text-sm text-muted-foreground">
                Waiting for the microscope…
              </p>
            )}
          </CardContent>
        </Card>

        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Mounted</CardTitle>
              <CardDescription>
                Stage micrometres to sample micrometres.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <div className="flex flex-wrap gap-2">
                <Badge variant="secondary">
                  {space?.holder ?? "nothing: the sample is the stage"}
                </Badge>
                <Badge variant="outline">mount {space?.mount_id ?? "…"}</Badge>
                {(space?.holders ?? []).length > 0 && (
                  <span className="text-xs text-muted-foreground">
                    can mount: {space?.holders.join(", ")}
                  </span>
                )}
              </div>
              {space && (
                <Matrix
                  rows={space.mount.slice(0, 3)}
                  columns={["x", "y", "z"]}
                  outputs={["x", "y", "z"]}
                />
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Systems</CardTitle>
              <CardDescription>
                Each with its axes: name, type, unit (none: indices).
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-1.5">
              {systems
                .filter((system) => !PLACE.test(system.name))
                .map((system) => (
                  <div
                    key={system.name}
                    className="flex flex-wrap items-center gap-1.5 text-sm"
                  >
                    <span className="w-44 font-mono">{system.name}</span>
                    {system.axes.length === 0 ? (
                      <span className="text-xs text-muted-foreground">
                        a point: no axes
                      </span>
                    ) : (
                      system.axes.map((axis) => (
                        <Badge
                          key={axis.name}
                          variant="outline"
                          className="font-mono"
                        >
                          {axis.name} · {axis.type}
                          {axis.unit ? ` · ${axis.unit}` : ""}
                        </Badge>
                      ))
                    )}
                  </div>
                ))}
              {placeEdges.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  and {placeEdges.length} places of the holder (well:A1 …), x
                  and y in micrometres
                </p>
              )}
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Where the detectors measure
            </CardTitle>
            <CardDescription>
              On the sample, now: an imaging detector's pixel (column, row,
              plane) to sample micrometres; a point detector's point.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2">
            {Object.values(space?.detectors ?? {}).map((placed) => (
              <div
                key={placed.detector}
                className="space-y-2 rounded-lg border p-3"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm">{placed.detector}</span>
                  <Badge variant={placed.calibrated ? "default" : "secondary"}>
                    {placed.calibrated ? "calibrated" : "predicted"}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    {placed.pixel_um.map(fmt).join(" × ")} µm per pixel
                  </span>
                </div>
                <Matrix
                  rows={placed.to_sample.slice(0, 3)}
                  columns={["col", "row", "plane"]}
                  outputs={["x", "y", "z"]}
                />
              </div>
            ))}
            {Object.values(space?.points ?? {}).map((point) => {
              const detector = readings.get(point.detector);
              return (
                <div
                  key={point.detector}
                  className="space-y-1 rounded-lg border p-3"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm">{point.detector}</span>
                    <Badge variant="secondary">at a point</Badge>
                    {detector && (
                      <span className="text-xs text-muted-foreground">
                        {detector.quantity}:{" "}
                        {detector.reading == null
                          ? "— (read while live)"
                          : `${detector.reading.toFixed(2)} ${detector.unit}`}
                      </span>
                    )}
                  </div>
                  <p className="font-mono text-xs">
                    x {fmt(point.x)} · y {fmt(point.y)} · z {fmt(point.z)} µm
                  </p>
                </div>
              );
            })}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Transformations</CardTitle>
            <CardDescription>
              Each edge as mikro has it. A BY_DIMENSION says nothing of an axis
              no part names; a part from fewer axes than it states is walked
              forwards only.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {otherEdges.map((edge, index) => (
              <TransformationCard key={index} edge={edge} systems={systems} />
            ))}
            {placeEdges.length > 0 && (
              <details className="rounded-lg border p-3">
                <summary className="cursor-pointer text-sm">
                  {placeEdges.length} places of the holder → sample
                </summary>
                <div className="mt-3 space-y-3">
                  {placeEdges.map((edge, index) => (
                    <TransformationCard
                      key={index}
                      edge={edge}
                      systems={systems}
                    />
                  ))}
                </div>
              </details>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
