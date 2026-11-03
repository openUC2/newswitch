import { useDetectorState } from "@/apps/default/hooks/states/DetectorState";
import { useHookState } from "@/apps/default/hooks/states/HookState";
import { useMoveState } from "@/apps/default/hooks/states/MoveState";
import { useOpticsState } from "@/apps/default/hooks/states/OpticsState";
import { useSourceState } from "@/apps/default/hooks/states/SourceState";
import { useSpaceState } from "@/apps/default/hooks/states/SpaceState";
import { useSwapState } from "@/apps/default/hooks/states/SwapState";
import { useTuneState } from "@/apps/default/hooks/states/TuneState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  append,
  channelOf,
  childrenOf,
  factsOf,
  newId,
  sameChannel,
  schedule,
  sequenceText,
  shift,
  starter,
  update,
  walk,
  type Block,
  type Facts,
  type LaneGroup,
  type Node,
  type Sequence,
  type States,
} from "@/lib/sequence/model";
import { cn } from "@/lib/utils";
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  GitBranch,
  Plus,
  RotateCcw,
  Trash2,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useState,
  type DragEvent,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

/**
 * A sequence editor: what to do and when, on a timeline whose lanes are the instrument's own.
 *
 * Every lane, channel, place, probe and hook here is read from the published states (`factsOf`);
 * nothing names a part of any microscope. A prototype: it lays a sequence out and checks it, and
 * runs nothing.
 */

const STORAGE = "newswitch.sequence";

const COLORS: Record<LaneGroup, string> = {
  stage: "bg-sky-500/70 border-sky-300",
  move: "bg-sky-700/60 border-sky-400",
  light: "bg-amber-500/70 border-amber-300",
  switch: "bg-violet-500/70 border-violet-300",
  tune: "bg-slate-500/70 border-slate-300",
  detector: "bg-emerald-500/80 border-emerald-300",
  probe: "bg-rose-500/70 border-rose-300",
  hook: "bg-slate-400/70 border-slate-200",
};

const LANE_HEIGHT = 30;
const LABEL_WIDTH = 150;

/** What the instrument's states say, as `factsOf` reads them. */
const useFacts = (): Facts => {
  const { data: moves } = useMoveState({ subscribe: true });
  const { data: swaps } = useSwapState({ subscribe: true });
  const { data: tunes } = useTuneState({ subscribe: true });
  const { data: sources } = useSourceState({ subscribe: true });
  const { data: detectors } = useDetectorState({ subscribe: true });
  const { data: optics } = useOpticsState({ subscribe: true });
  const { data: space } = useSpaceState({ subscribe: true });
  const { data: hooks } = useHookState({ subscribe: true });
  return useMemo(
    () =>
      factsOf({
        moves: moves?.moves,
        swaps: swaps?.swaps,
        tunes: tunes?.tunes,
        sources: sources?.sources,
        detectors: detectors?.detectors,
        channels: optics?.channels,
        samples: space?.samples,
        points: space?.points,
        placements: space?.detectors,
        hooks: hooks?.registered_hooks,
      } as States),
    [moves, swaps, tunes, sources, detectors, optics, space, hooks],
  );
};

const load = (): Sequence | null => {
  try {
    const text = localStorage.getItem(STORAGE);
    return text ? (JSON.parse(text) as Sequence) : null;
  } catch {
    return null;
  }
};

const save = (sequence: Sequence) => {
  try {
    localStorage.setItem(STORAGE, JSON.stringify(sequence));
  } catch {
    // nowhere to keep it: it lives as long as the page
  }
};

/** What a node does, in a few words, for the outline. */
const describe = (node: Node, facts: Facts): string => {
  switch (node.kind) {
    case "expose":
      return (
        channelOf(facts, node.channel)?.name ??
        `${node.channel.source} → ${node.channel.detector}`
      );
    case "read":
      return `read ${node.probe}`;
    case "stream":
      return `stream ${node.probe}`;
    case "set":
      return `${node.variable} → ${node.value}${node.for_s !== undefined ? ` for ${node.for_s * 1000} ms` : ""}`;
    case "move":
      return `move to ${node.to}`;
    case "hook":
      return node.hook;
    case "wait":
      return `wait ${node.for_s} s`;
    case "repeat":
      return `repeat ×${node.times}, every ${node.every_s} s`;
    case "for_each_position":
      return `for each of ${node.places.length} places`;
    case "for_each_z":
      return `for each z: ${node.range_um} µm, ${node.step_um} µm apart`;
    case "parallel":
      return `at the same time: ${node.branches.length} branches`;
  }
};

const holds = (node: Node) => node.kind === "parallel" || "body" in node;

/** One thing to add, from the palette: by a click, or dragged onto the outline. */
const Item = ({
  label,
  hint,
  make,
  onAdd,
}: {
  label: string;
  hint?: string;
  make: () => Node;
  onAdd: (node: Node) => void;
}) => (
  <button
    type="button"
    draggable
    onDragStart={(e: DragEvent) => {
      e.dataTransfer.setData("application/json", JSON.stringify(make()));
    }}
    onClick={() => onAdd(make())}
    className="flex w-full flex-col rounded-md border border-border/60 bg-muted/30 px-2 py-1 text-left hover:bg-muted"
  >
    <span className="truncate text-xs">{label}</span>
    {hint && (
      <span className="truncate text-[10px] text-muted-foreground">{hint}</span>
    )}
  </button>
);

const Group = ({ title, children }: { title: string; children: ReactNode }) => (
  <div className="space-y-1">
    <div className="px-1 text-[10px] font-medium uppercase tracking-[0.2em] text-muted-foreground">
      {title}
    </div>
    {children}
  </div>
);

const Palette = ({
  facts,
  onAdd,
}: {
  facts: Facts;
  onAdd: (node: Node) => void;
}) => (
  <div className="space-y-4">
    {facts.samples.map((sample) => (
      <Group key={sample} title={`expose · ${sample}`}>
        {facts.channels
          .filter((c) => c.sample === sample)
          .map((c) => (
            <Item
              key={`${c.ref.source}-${c.ref.detector}-${JSON.stringify(c.ref.swaps)}`}
              label={c.name}
              hint={`${c.ref.source} → ${c.ref.detector}`}
              make={() => ({ id: newId(), kind: "expose", channel: c.ref })}
              onAdd={onAdd}
            />
          ))}
      </Group>
    ))}
    {facts.probes.length > 0 && (
      <Group title="probes">
        {facts.probes.map((p) => (
          <div key={p.name} className="grid grid-cols-2 gap-1">
            <Item
              label={`read ${p.name}`}
              hint={p.quantity}
              make={() => ({ id: newId(), kind: "read", probe: p.name })}
              onAdd={onAdd}
            />
            {p.block_s !== undefined && (
              <Item
                label={`stream ${p.name}`}
                hint="the whole time"
                make={() => ({ id: newId(), kind: "stream", probe: p.name })}
                onAdd={onAdd}
              />
            )}
          </div>
        ))}
      </Group>
    )}
    <Group title="set">
      {facts.sets.map((set) => (
        <Item
          key={set.variable}
          label={set.variable}
          hint={
            set.options
              ? set.options.map((o) => o.label).join(" · ")
              : `${set.value} ${set.unit}`
          }
          make={() => ({
            id: newId(),
            kind: "set",
            variable: set.variable,
            value: set.options?.[0]?.slot ?? set.value,
            ...(set.options ? {} : { for_s: 0.005 }),
          })}
          onAdd={onAdd}
        />
      ))}
    </Group>
    {facts.places.length > 0 && (
      <Group title="move to">
        <div className="grid grid-cols-3 gap-1">
          {facts.places.slice(0, 48).map((place) => (
            <Item
              key={place.system}
              label={place.label}
              make={() => ({ id: newId(), kind: "move", to: place.system })}
              onAdd={onAdd}
            />
          ))}
        </div>
      </Group>
    )}
    <Group title="flow">
      <Item
        label="repeat"
        hint="every so many seconds: t"
        make={() => ({
          id: newId(),
          kind: "repeat",
          times: 3,
          every_s: 2,
          body: [],
        })}
        onAdd={onAdd}
      />
      <Item
        label="for each position"
        hint="a dataset each"
        make={() => ({
          id: newId(),
          kind: "for_each_position",
          places: facts.places.slice(0, 2).map((p) => p.system),
          body: [],
        })}
        onAdd={onAdd}
      />
      <Item
        label="for each z"
        hint="z"
        make={() => ({
          id: newId(),
          kind: "for_each_z",
          range_um: 10,
          step_um: 2,
          body: [],
        })}
        onAdd={onAdd}
      />
      <Item
        label="at the same time"
        hint="branches side by side"
        make={() => ({ id: newId(), kind: "parallel", branches: [[], []] })}
        onAdd={onAdd}
      />
      <Item
        label="wait"
        make={() => ({ id: newId(), kind: "wait", for_s: 1 })}
        onAdd={onAdd}
      />
      {facts.hooks.map((hook) => (
        <Item
          key={hook}
          label={hook}
          hint="hook"
          make={() => ({ id: newId(), kind: "hook", hook })}
          onAdd={onAdd}
        />
      ))}
    </Group>
  </div>
);

/** The timeline: a lane per variable and detector that the sequence uses, time across. */
const Timeline = ({
  facts,
  sequence,
  selected,
  onSelect,
}: {
  facts: Facts;
  sequence: Sequence;
  selected: string | null;
  onSelect: (id: string) => void;
}) => {
  const laid = useMemo(() => schedule(sequence, facts), [sequence, facts]);
  const used = new Set(laid.blocks.map((b) => b.lane));
  const [all, setAll] = useState(false);
  const lanes = facts.lanes.filter((lane) => all || used.has(lane.id));
  const [zoom, setZoom] = useState(1);
  const end = Math.max(laid.end, 1);
  const width = 900 * zoom;
  const x = (s: number) => (s / end) * width;
  const clashing = new Set(
    laid.conflicts
      .flatMap((c) => [c.a, c.b])
      .map((b: Block) => `${b.node}|${b.lane}|${b.start}`),
  );
  const depth = Math.max(0, ...laid.spans.map((s) => s.depth + 1));
  const ticks = Array.from({ length: 11 }, (_, i) => (end * i) / 10);
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        <span>
          {end.toFixed(2)} s · {laid.blocks.length} blocks
        </span>
        <label className="flex items-center gap-1">
          zoom
          <input
            type="range"
            min={1}
            max={20}
            step={0.5}
            value={zoom}
            onChange={(e) => setZoom(Number(e.target.value))}
          />
        </label>
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={all}
            onChange={(e) => setAll(e.target.checked)}
          />
          every lane
        </label>
      </div>
      <div className="overflow-x-auto rounded-lg border border-border/60 bg-background">
        <div style={{ width: LABEL_WIDTH + width + 20 }} className="relative">
          {/* the clock */}
          <div
            className="relative h-6 border-b border-border/40"
            style={{ marginLeft: LABEL_WIDTH }}
          >
            {ticks.map((t) => (
              <span
                key={t}
                className="absolute top-1 text-[10px] tabular-nums text-muted-foreground"
                style={{ left: x(t) }}
              >
                {t < 10 ? t.toFixed(2) : t.toFixed(1)} s
              </span>
            ))}
          </div>
          {/* the loops, as brackets */}
          <div
            className="relative border-b border-border/40"
            style={{ height: depth * 18 + 4, marginLeft: LABEL_WIDTH }}
          >
            {laid.spans.map((span) => (
              <button
                type="button"
                key={span.node}
                onClick={() => onSelect(span.node)}
                className={cn(
                  "absolute truncate rounded border px-1 text-left text-[10px]",
                  selected === span.node
                    ? "border-primary bg-primary/30"
                    : "border-border bg-muted/60",
                )}
                style={{
                  left: x(span.start),
                  width: Math.max(4, x(span.end) - x(span.start)),
                  top: span.depth * 18 + 2,
                  height: 16,
                }}
                title={span.label}
              >
                {span.label}
              </button>
            ))}
          </div>
          {lanes.map((lane) => (
            <div
              key={lane.id}
              className="relative flex border-b border-border/30"
              style={{ height: LANE_HEIGHT }}
            >
              <div
                className="sticky left-0 z-10 flex shrink-0 flex-col justify-center border-r border-border/40 bg-background px-2"
                style={{ width: LABEL_WIDTH }}
              >
                <span className="truncate font-mono text-[11px]">
                  {lane.label}
                </span>
                <span className="truncate text-[9px] text-muted-foreground">
                  {lane.group}
                  {lane.sample ? ` · ${lane.sample}` : ""}
                </span>
              </div>
              <div className="relative flex-1">
                {laid.blocks
                  .filter((b) => b.lane === lane.id)
                  .map((b, i) => (
                    <button
                      type="button"
                      key={`${b.node}-${i}`}
                      onClick={() => onSelect(b.node)}
                      title={`${b.label}: ${b.start.toFixed(3)}–${b.end.toFixed(3)} s${b.unknown ? " (how long is not known before it runs)" : ""}`}
                      className={cn(
                        "absolute top-1 truncate rounded border px-1 text-left text-[10px] text-white",
                        COLORS[lane.group],
                        b.condition &&
                          "opacity-40 [background-image:repeating-linear-gradient(45deg,transparent_0,transparent_4px,rgba(255,255,255,.25)_4px,rgba(255,255,255,.25)_8px)]",
                        b.unknown && "border-dashed",
                        b.late && "ring-2 ring-amber-400",
                        clashing.has(`${b.node}|${b.lane}|${b.start}`) &&
                          "ring-2 ring-red-500 opacity-100",
                        selected === b.node &&
                          "outline outline-2 outline-white",
                      )}
                      style={{
                        left: x(b.start),
                        width: Math.max(3, x(b.end) - x(b.start)),
                        height: LANE_HEIGHT - 8,
                      }}
                    >
                      {b.label}
                    </button>
                  ))}
              </div>
            </div>
          ))}
        </div>
      </div>
      {(laid.conflicts.length > 0 || laid.problems.length > 0) && (
        <ul className="space-y-1 text-xs">
          {laid.conflicts.map((c, i) => (
            <li key={i} className="text-red-400">
              {c.lane}: {c.a.label} ({c.a.start.toFixed(3)} s) and {c.b.label} (
              {c.b.start.toFixed(3)} s) want it at once
            </li>
          ))}
          {laid.problems.map((p, i) => (
            <li key={`p${i}`} className="text-amber-400">
              {p}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

/** The sequence as a tree: select, reorder, drop into. */
const Outline = ({
  facts,
  nodes,
  selected,
  depth,
  onSelect,
  onChange,
  onDrop,
}: {
  facts: Facts;
  nodes: Node[];
  selected: string | null;
  depth: number;
  onSelect: (id: string) => void;
  onChange: (id: string, change: (node: Node) => Node | null) => void;
  onDrop: (into: string, node: Node) => void;
}) => (
  <div className="space-y-0.5">
    {nodes.map((node) => (
      <div key={node.id}>
        <div
          onClick={() => onSelect(node.id)}
          onDragOver={(e) => holds(node) && e.preventDefault()}
          onDrop={(e) => {
            const text = e.dataTransfer.getData("application/json");
            if (text && holds(node)) {
              e.stopPropagation();
              onDrop(node.id, JSON.parse(text) as Node);
            }
          }}
          className={cn(
            "flex cursor-pointer items-center gap-1 rounded px-1 py-0.5 text-xs",
            selected === node.id ? "bg-primary/20" : "hover:bg-muted/60",
          )}
          style={{ paddingLeft: depth * 14 + 4 }}
        >
          <span className="w-24 shrink-0 font-mono text-[10px] text-muted-foreground">
            {node.kind}
          </span>
          <span className="min-w-0 flex-1 truncate">
            {describe(node, facts)}
          </span>
        </div>
        {node.kind === "parallel"
          ? node.branches.map((branch, i) => (
              <div key={i}>
                <div
                  className="text-[10px] text-muted-foreground"
                  style={{ paddingLeft: (depth + 1) * 14 + 4 }}
                >
                  <GitBranch className="mr-1 inline size-3" />
                  branch {i + 1}
                </div>
                <Outline
                  facts={facts}
                  nodes={branch}
                  selected={selected}
                  depth={depth + 2}
                  onSelect={onSelect}
                  onChange={onChange}
                  onDrop={onDrop}
                />
              </div>
            ))
          : holds(node) && (
              <Outline
                facts={facts}
                nodes={childrenOf(node)}
                selected={selected}
                depth={depth + 1}
                onSelect={onSelect}
                onChange={onChange}
                onDrop={onDrop}
              />
            )}
      </div>
    ))}
  </div>
);

const Field = ({ label, children }: { label: string; children: ReactNode }) => (
  <label className="flex flex-col gap-1">
    <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
      {label}
    </span>
    {children}
  </label>
);

const SELECT = "h-8 rounded-md border border-input bg-background px-2 text-xs";

const NumberInput = ({
  value,
  onChange,
  step = 1,
}: {
  value: number | undefined;
  onChange: (value: number | undefined) => void;
  step?: number;
}) => (
  <Input
    type="number"
    className="h-8 text-xs"
    step={step}
    value={value ?? ""}
    onChange={(e) =>
      onChange(e.target.value === "" ? undefined : Number(e.target.value))
    }
  />
);

/** What can be said of the node selected. */
const Inspector = ({
  facts,
  node,
  onChange,
}: {
  facts: Facts;
  node: Node;
  onChange: (change: (node: Node) => Node | null) => void;
}) => {
  const set = (patch: Partial<Node>) =>
    onChange((n) => ({ ...n, ...patch }) as Node);
  const at =
    "at_s" in node ||
    node.kind === "expose" ||
    node.kind === "read" ||
    node.kind === "set" ||
    node.kind === "move" ? (
      <Field label="at (s on the clock; empty: after what comes before)">
        <NumberInput
          step={0.1}
          value={(node as { at_s?: number }).at_s}
          onChange={(at_s) => set({ at_s } as Partial<Node>)}
        />
      </Field>
    ) : null;
  switch (node.kind) {
    case "expose":
      return (
        <div className="space-y-2">
          <Field label="channel">
            <select
              className={SELECT}
              value={facts.channels.findIndex((c) =>
                sameChannel(c.ref, node.channel),
              )}
              onChange={(e) =>
                set({ channel: facts.channels[Number(e.target.value)].ref })
              }
            >
              {facts.channels.map((c, i) => (
                <option key={i} value={i}>
                  {c.name} ({c.sample})
                </option>
              ))}
            </select>
          </Field>
          {at}
        </div>
      );
    case "read":
    case "stream":
      return (
        <div className="space-y-2">
          <Field label="probe">
            <select
              className={SELECT}
              value={node.probe}
              onChange={(e) => set({ probe: e.target.value })}
            >
              {facts.probes.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name} · {p.quantity}
                </option>
              ))}
            </select>
          </Field>
          {node.kind === "read" && at}
        </div>
      );
    case "set": {
      const fact = facts.sets.find((s) => s.variable === node.variable);
      return (
        <div className="space-y-2">
          <Field label="variable">
            <select
              className={SELECT}
              value={node.variable}
              onChange={(e) => set({ variable: e.target.value })}
            >
              {facts.sets.map((s) => (
                <option key={s.variable} value={s.variable}>
                  {s.variable}
                </option>
              ))}
            </select>
          </Field>
          <Field label={`to${fact?.unit ? ` (${fact.unit})` : ""}`}>
            {fact?.options ? (
              <select
                className={SELECT}
                value={node.value}
                onChange={(e) => set({ value: Number(e.target.value) })}
              >
                {fact.options.map((o) => (
                  <option key={o.slot} value={o.slot}>
                    {o.label}
                  </option>
                ))}
              </select>
            ) : (
              <NumberInput
                step={0.1}
                value={node.value}
                onChange={(value) => set({ value: value ?? 0 })}
              />
            )}
          </Field>
          <Field label="for (ms; empty: it stays)">
            <NumberInput
              step={1}
              value={node.for_s === undefined ? undefined : node.for_s * 1000}
              onChange={(ms) =>
                set({ for_s: ms === undefined ? undefined : ms / 1000 })
              }
            />
          </Field>
          {at}
        </div>
      );
    }
    case "move":
      return (
        <div className="space-y-2">
          <Field label="to">
            <select
              className={SELECT}
              value={node.to}
              onChange={(e) => set({ to: e.target.value })}
            >
              {facts.places.map((p) => (
                <option key={p.system} value={p.system}>
                  {p.system}
                </option>
              ))}
            </select>
          </Field>
          {at}
        </div>
      );
    case "hook":
      return (
        <Field label="hook">
          <select
            className={SELECT}
            value={node.hook}
            onChange={(e) => set({ hook: e.target.value })}
          >
            {facts.hooks.map((h) => (
              <option key={h} value={h}>
                {h}
              </option>
            ))}
          </select>
        </Field>
      );
    case "wait":
      return (
        <Field label="for (s)">
          <NumberInput
            step={0.1}
            value={node.for_s}
            onChange={(for_s) => set({ for_s: for_s ?? 0 })}
          />
        </Field>
      );
    case "repeat":
      return (
        <div className="grid grid-cols-2 gap-2">
          <Field label="times">
            <NumberInput
              value={node.times}
              onChange={(times) => set({ times: Math.max(1, times ?? 1) })}
            />
          </Field>
          <Field label="every (s)">
            <NumberInput
              step={0.1}
              value={node.every_s}
              onChange={(every_s) => set({ every_s: every_s ?? 0 })}
            />
          </Field>
        </div>
      );
    case "for_each_z":
      return (
        <div className="grid grid-cols-2 gap-2">
          <Field label="range (µm)">
            <NumberInput
              value={node.range_um}
              onChange={(range_um) => set({ range_um: range_um ?? 0 })}
            />
          </Field>
          <Field label="step (µm)">
            <NumberInput
              step={0.5}
              value={node.step_um}
              onChange={(step_um) =>
                set({ step_um: Math.max(0.1, step_um ?? 1) })
              }
            />
          </Field>
        </div>
      );
    case "for_each_position":
      return (
        <Field label="places">
          <div className="grid max-h-48 grid-cols-3 gap-1 overflow-y-auto">
            {facts.places.map((p) => (
              <label
                key={p.system}
                className="flex items-center gap-1 text-[11px]"
              >
                <input
                  type="checkbox"
                  checked={node.places.includes(p.system)}
                  onChange={(e) =>
                    set({
                      places: e.target.checked
                        ? [...node.places, p.system]
                        : node.places.filter((s) => s !== p.system),
                    })
                  }
                />
                {p.label}
              </label>
            ))}
          </div>
        </Field>
      );
    case "parallel":
      return (
        <Button
          size="sm"
          variant="outline"
          onClick={() =>
            onChange((n) =>
              n.kind === "parallel"
                ? { ...n, branches: [...n.branches, []] }
                : n,
            )
          }
        >
          <Plus className="mr-1 size-3" /> a branch
        </Button>
      );
  }
};

export function SequencePage() {
  const { t } = useTranslation();
  const facts = useFacts();
  const [edited, setSequence] = useState<Sequence | null>(load);
  const [selected, setSelected] = useState<string | null>(null);

  // Until it is edited, a first sequence of what the instrument has said it has.
  const ready = facts.lanes.length > 1 && facts.channels.length > 0;
  const first = useMemo(() => (ready ? starter(facts) : null), [ready, facts]);
  const sequence = edited ?? first;
  useEffect(() => {
    if (edited) save(edited);
  }, [edited]);

  if (!sequence) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        {t("sequence.waiting", "Reading the instrument…")}
      </div>
    );
  }
  const node = selected
    ? walk(sequence.body).find((n) => n.id === selected)
    : undefined;
  const into = node && holds(node) ? node.id : undefined;
  const change = (id: string, edit: (n: Node) => Node | null) =>
    setSequence({ ...sequence, body: update(sequence.body, id, edit) });
  const add = (added: Node, container = into) => {
    setSequence({ ...sequence, body: append(sequence.body, added, container) });
    setSelected(added.id);
  };

  return (
    <div className="flex h-full w-full flex-col gap-3 overflow-hidden p-4">
      <div className="flex items-center gap-3">
        <Link
          to="/"
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          {t("sequence.back", "Back to microscope")}
        </Link>
        <span className="text-lg font-semibold">
          {t("sequence.title", "Sequence")}
        </span>
        <Input
          className="h-8 max-w-56 text-sm"
          value={sequence.name}
          onChange={(e) => setSequence({ ...sequence, name: e.target.value })}
        />
        <Badge variant="outline" className="text-[10px]">
          {t(
            "sequence.prototype",
            "prototype: laid out and checked, never run",
          )}
        </Badge>
        <Button
          size="sm"
          variant="ghost"
          className="ml-auto"
          onClick={() => {
            setSequence(starter(facts));
            setSelected(null);
          }}
        >
          <RotateCcw className="mr-1 size-3.5" />
          {t("sequence.startOver", "Start over")}
        </Button>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-[240px_minmax(0,1fr)_320px] gap-3">
        <ScrollArea className="min-h-0 rounded-lg border border-border/60 p-2">
          <div className="pb-1 text-[11px] text-muted-foreground">
            {t(
              "sequence.paletteHint",
              "Click to add, or drag onto a loop in the outline",
            )}
            {into ? ` · into ${describe(node!, facts)}` : ""}
          </div>
          <Palette facts={facts} onAdd={(n) => add(n)} />
        </ScrollArea>
        <div className="flex min-h-0 flex-col gap-3 overflow-y-auto">
          <Timeline
            facts={facts}
            sequence={sequence}
            selected={selected}
            onSelect={setSelected}
          />
          <div
            className="rounded-lg border border-border/60 p-2"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              const text = e.dataTransfer.getData("application/json");
              if (text) add(JSON.parse(text) as Node, undefined);
            }}
          >
            <div className="mb-1 flex items-center gap-1">
              <span className="text-[10px] font-medium uppercase tracking-[0.2em] text-muted-foreground">
                outline
              </span>
              {node && (
                <span className="ml-auto flex gap-1">
                  <Button
                    size="icon"
                    variant="ghost"
                    className="size-6"
                    onClick={() =>
                      setSequence({
                        ...sequence,
                        body: shift(sequence.body, node.id, -1),
                      })
                    }
                  >
                    <ArrowUp className="size-3" />
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="size-6"
                    onClick={() =>
                      setSequence({
                        ...sequence,
                        body: shift(sequence.body, node.id, 1),
                      })
                    }
                  >
                    <ArrowDown className="size-3" />
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="size-6"
                    onClick={() => {
                      change(node.id, () => null);
                      setSelected(null);
                    }}
                  >
                    <Trash2 className="size-3" />
                  </Button>
                </span>
              )}
            </div>
            <Outline
              facts={facts}
              nodes={sequence.body}
              selected={selected}
              depth={0}
              onSelect={(id) => setSelected(id === selected ? null : id)}
              onChange={change}
              onDrop={(container, added) => add(added, container)}
            />
          </div>
        </div>
        <div className="flex min-h-0 flex-col gap-3">
          <div className="rounded-lg border border-border/60 p-3">
            <div className="mb-2 text-[10px] font-medium uppercase tracking-[0.2em] text-muted-foreground">
              {node
                ? node.kind
                : t("sequence.nothingSelected", "select a block")}
            </div>
            {node && (
              <Inspector
                facts={facts}
                node={node}
                onChange={(edit) => change(node.id, edit)}
              />
            )}
          </div>
          <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-border/60">
            <div className="px-3 pt-2 text-[10px] font-medium uppercase tracking-[0.2em] text-muted-foreground">
              {t("sequence.asText", "as text")}
            </div>
            <pre className="min-h-0 flex-1 overflow-auto p-3 font-mono text-[11px] leading-relaxed">
              {sequenceText(sequence, facts)}
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
}
