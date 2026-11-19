import { useSwap } from "@/apps/default/hooks/actions";
import { useSwapState } from "@/apps/default/hooks/states/SwapState";
import { Button } from "@/components/ui/button";
import { entriesOf } from "@/lib/microscope/values";

/** Everything a swap can put in place, each as a card of what it can be. */
export function SwapsControl() {
  const { data } = useSwapState({ subscribe: true });
  const { assign, isLoading } = useSwap();
  return (
    <div className="flex flex-col gap-3">
      {entriesOf(data?.swaps).map((swap) => (
        <div
          key={swap.name}
          className="flex flex-col gap-1 rounded-2xl border border-border/60 bg-card/70 p-4 shadow-xl"
        >
          <span className="mb-1 text-[10px] font-medium uppercase tracking-[0.2em] text-muted-foreground">
            {swap.name.split(".")[0].replaceAll("_", " ")}
          </span>
          {swap.options.map((option) =>
            option.slot === swap.current ? (
              <div
                key={option.slot}
                className="flex items-center gap-3 rounded-xl border border-success/40 bg-success/10 px-3 py-2"
              >
                <span className="size-2 rounded-full bg-success shadow-[0_0_10px_2px] shadow-success/60" />
                <span className="text-sm font-medium">{option.label}</span>
                {option.facts.center && (
                  <span className="ml-auto text-xs tabular-nums text-muted-foreground">
                    {option.facts.center} / {option.facts.width}
                  </span>
                )}
              </div>
            ) : (
              <Button
                key={option.slot}
                variant="ghost"
                className="w-full justify-start rounded-xl past:hidden"
                disabled={isLoading}
                onClick={() => assign({ name: swap.name, slot: option.slot })}
              >
                {option.label}
              </Button>
            ),
          )}
        </div>
      ))}
    </div>
  );
}
