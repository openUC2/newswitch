import { useSwapState } from "@/apps/default/hooks/states/SwapState";
import { entriesOf } from "@/lib/microscope/values";
import { VariableControl } from "./VariableControl";

/** Everything a swap can put in place. */
export function SwapsControl() {
  const { data } = useSwapState({ subscribe: true });
  return (
    <div className="space-y-3">
      {entriesOf(data?.swaps).map((swap) => (
        <VariableControl key={swap.name} name={swap.name} />
      ))}
    </div>
  );
}
