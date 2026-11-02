import {
  MoveDefinition,
  MoveHomeDefinition,
} from "@/apps/default/hooks/actions";
import type { MoveValue } from "@/apps/default/hooks/states/MoveState";
import { useMotionLock } from "@/apps/default/hooks/locks";
import { ActionButton } from "@/components/ActionButton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useStage } from "@/lib/microscope/values";
import { SampleSwitch } from "@/lib/microscope/sample";
import { cn } from "@/lib/utils";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Home,
  Move,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ProgressDisplay } from "../TaskDisplay";
import { VariableControl } from "./VariableControl";

const percent = (move: MoveValue) => {
  if (move.minimum == null || move.maximum == null) return null;
  const range = move.maximum - move.minimum;
  return range > 0 ? ((move.value - move.minimum) / range) * 100 : null;
};

const Readout = ({ move }: { move: MoveValue }) => (
  <div className="relative overflow-hidden rounded-lg bg-muted/50 p-2 text-center">
    {percent(move) !== null && (
      <div
        className={cn("absolute bottom-0 left-0 h-1 bg-primary transition-all")}
        style={{ width: `${percent(move)}%` }}
      />
    )}
    <div className="truncate text-xs text-muted-foreground">{move.name}</div>
    <div className="font-mono text-sm font-bold">
      {Number(move.value.toFixed(2))}
    </div>
    <div className="text-xs text-muted-foreground">{move.unit}</div>
  </div>
);

/** A move's steps: its own finest step, and tenfold up. */
const stepsOf = (move?: MoveValue) => {
  const first = move?.step ?? 1;
  return [first, first * 10, first * 100, first * 1000];
};

/** Everything that moves. What moves the view gets a pad and what focuses it up and down, when it
 * is clear which those are; anything else, a control of its own. */
export function MoveControl() {
  const { t } = useTranslation();
  const stage = useStage();
  const activeTaskId = useMotionLock().lockingTaskId;
  const [x] = stage.x.length === 1 ? stage.x : [];
  const [y] = stage.y.length === 1 ? stage.y : [];
  const [focus] = stage.focus.length === 1 ? stage.focus : [];
  const steps = stepsOf(x ?? y);
  const [stepIndex, setStepIndex] = useState(1);
  const step = steps[stepIndex];
  const [focusStep, setFocusStep] = useState(focus?.step ?? 1);
  const singles = [
    ...(x ? [] : stage.x),
    ...(y ? [] : stage.y),
    ...(focus ? [] : stage.focus),
    ...stage.rest,
  ];
  const everything = [...stage.x, ...stage.y, ...stage.focus, ...stage.rest];

  const by = (move: MoveValue | undefined, amount: number) => ({
    targets: move ? { [move.name]: amount } : {},
    relative: true,
  });

  return (
    <div className="w-full space-y-4">
      <div className="flex items-center gap-2">
        <Move className="h-4 w-4" />
        <span className="text-sm font-medium">
          {t("microscope.stageControl")}
        </span>
        {/* With several samples, which one's stage: the same pick as the stage view's. */}
        <SampleSwitch />
      </div>

      <div className="grid grid-cols-3 gap-2">
        {everything.map((move) => (
          <Readout key={move.name} move={move} />
        ))}
      </div>

      {x && y && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-end gap-1">
            {steps.map((size, index) => (
              <Button
                key={size}
                size="sm"
                variant={stepIndex === index ? "default" : "outline"}
                onClick={() => setStepIndex(index)}
                className="h-7 px-2 text-xs"
              >
                {size} {x.unit}
              </Button>
            ))}
          </div>
          <div className="flex justify-center">
            <div className="grid grid-cols-3 gap-1">
              <div />
              <ActionButton
                action={MoveDefinition}
                args={by(y, step)}
                variant="outline"
                size="icon"
                className="h-10 w-10"
              >
                <ArrowUp className="h-5 w-5" />
              </ActionButton>
              <div />
              <ActionButton
                action={MoveDefinition}
                args={by(x, -step)}
                variant="outline"
                size="icon"
                className="h-10 w-10"
              >
                <ArrowLeft className="h-5 w-5" />
              </ActionButton>
              <ActionButton
                action={MoveHomeDefinition}
                args={{}}
                variant="secondary"
                size="icon"
                className="h-10 w-10"
              >
                <Home className="h-4 w-4" />
              </ActionButton>
              <ActionButton
                action={MoveDefinition}
                args={by(x, step)}
                variant="outline"
                size="icon"
                className="h-10 w-10"
              >
                <ArrowRight className="h-5 w-5" />
              </ActionButton>
              <div />
              <ActionButton
                action={MoveDefinition}
                args={by(y, -step)}
                variant="outline"
                size="icon"
                className="h-10 w-10"
              >
                <ArrowDown className="h-5 w-5" />
              </ActionButton>
              <div />
            </div>
          </div>
        </div>
      )}

      {focus && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              {t("microscope.focus")} ({focus.name})
            </span>
            <div className="flex items-center gap-1">
              <Input
                type="number"
                value={focusStep}
                onChange={(e) => setFocusStep(parseFloat(e.target.value) || 0)}
                className="h-7 w-16 text-xs"
              />
              <span className="text-xs text-muted-foreground">
                {focus.unit}
              </span>
            </div>
          </div>
          <div className="flex gap-2">
            <ActionButton
              action={MoveDefinition}
              args={by(focus, focusStep)}
              variant="outline"
              className="h-9 flex-1"
            >
              <ArrowUp className="mr-1 h-3 w-3" />
              {t("microscope.up")}
            </ActionButton>
            <ActionButton
              action={MoveDefinition}
              args={by(focus, -focusStep)}
              variant="outline"
              className="h-9 flex-1"
            >
              <ArrowDown className="mr-1 h-3 w-3" />
              {t("microscope.down")}
            </ActionButton>
          </div>
        </div>
      )}

      {singles.map((move) => (
        <VariableControl key={move.name} name={move.name} />
      ))}

      <ProgressDisplay activeTaskId={activeTaskId} />
    </div>
  );
}
