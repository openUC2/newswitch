import { useMoveOne, useSwap, useTune } from "@/apps/default/hooks/actions";
import {
  useMoveState,
  type MoveValue,
} from "@/apps/default/hooks/states/MoveState";
import {
  useSwapState,
  type SwapValue,
} from "@/apps/default/hooks/states/SwapState";
import {
  useTuneState,
  type TuneValue,
} from "@/apps/default/hooks/states/TuneState";
import { OptimisticSlider } from "@/components/ui/optimistic_slider";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const short = (name: string) => name.split(".").slice(1).join(".");

const SwapRow = ({ variable }: { variable: SwapValue }) => {
  const { assign, isLoading } = useSwap();
  return (
    <div className="space-y-1">
      <div className="text-xs text-muted-foreground">{variable.name}</div>
      <div className="flex flex-wrap gap-1">
        {variable.options.map((option) => (
          <Button
            key={option.slot}
            size="sm"
            variant={option.slot === variable.current ? "default" : "outline"}
            disabled={isLoading}
            onClick={() => assign({ name: variable.name, slot: option.slot })}
            className="h-7 px-2 text-xs"
          >
            {option.label}
          </Button>
        ))}
      </div>
    </div>
  );
};

const Reading = ({ value, unit }: { value: number; unit: string }) => (
  <span className="font-mono text-xs tabular-nums">
    {Number(value.toFixed(3))} {unit}
  </span>
);

const NumberRow = ({
  variable,
  save,
  disabled,
}: {
  variable: MoveValue | TuneValue;
  save: (to: number) => Promise<unknown>;
  disabled: boolean;
}) => (
  <div className="space-y-1">
    <div className="flex items-center justify-between gap-2">
      <span className="text-xs text-muted-foreground">
        {short(variable.name)}
      </span>
      <Reading value={variable.current} unit={variable.unit} />
    </div>
    {variable.minimum != null && variable.maximum != null && (
      <OptimisticSlider
        value={[variable.current]}
        onSave={(v) => save(v[0])}
        min={variable.minimum}
        max={variable.maximum}
        step={variable.step ?? undefined}
        disabled={disabled}
      />
    )}
  </div>
);

const MoveRow = ({ variable }: { variable: MoveValue }) => {
  const { assign, isLoading } = useMoveOne();
  return (
    <NumberRow
      variable={variable}
      save={(to) => assign({ name: variable.name, to })}
      disabled={isLoading}
    />
  );
};

export const TuneRow = ({ variable }: { variable: TuneValue }) => {
  const { assign, isLoading } = useTune();
  return (
    <NumberRow
      variable={variable}
      save={(to) => assign({ name: variable.name, to })}
      disabled={isLoading}
    />
  );
};

/** The control of one variable, whatever it is: by its name in the description. */
export function VariableControl({
  name,
  className,
}: {
  name: string;
  className?: string;
}) {
  const [cube, variable] = name.split(/\.(.*)/s);
  const { data: moves } = useMoveState({ subscribe: true });
  const { data: swaps } = useSwapState({ subscribe: true });
  const { data: tunes } = useTuneState({ subscribe: true });
  const move = moves?.moves[cube]?.[variable];
  const swap = swaps?.swaps[cube]?.[variable];
  const tune = tunes?.tunes[cube]?.[variable];

  return (
    <div className={cn("w-full", className)}>
      {move && <MoveRow variable={move} />}
      {swap && <SwapRow variable={swap} />}
      {tune && <TuneRow variable={tune} />}
    </div>
  );
}
