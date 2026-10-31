"use client";

import { cn } from "@/lib/utils";
import * as SliderPrimitive from "@radix-ui/react-slider";
import * as React from "react";

interface OptimisticSliderProps extends React.ComponentProps<
  typeof SliderPrimitive.Root
> {
  onSave?: (value: number[]) => Promise<unknown>;
}

function OptimisticSlider({
  className,
  defaultValue,
  value,
  min = 0,
  max = 100,
  onSave,
  onValueChange,
  onValueCommit,
  ...props
}: OptimisticSliderProps) {
  // Local state for the "live" dragging position
  const [internalValue, setInternalValue] = React.useState<number[]>(
    value || defaultValue || [min],
  );
  // Snapshot for reverting if the server fails
  const [stableValue, setStableValue] = React.useState<number[]>(
    value || defaultValue || [min],
  );
  const [isPending, setIsPending] = React.useState(false);

  // Keep internal state in sync if external 'value' prop updates
  React.useEffect(() => {
    if (value) {
      setInternalValue(value);
      setStableValue(value);
    }
  }, [value]);

  const handleValueChange = (newValues: number[]) => {
    // Update UI immediately while dragging
    setInternalValue(newValues);
    if (onValueChange) onValueChange(newValues);
  };

  const handleValueCommit = async (committedValues: number[]) => {
    if (onValueCommit) onValueCommit(committedValues);
    if (!onSave) return;

    setIsPending(true);
    try {
      await onSave(committedValues);
      // Success: update the "stable" snapshot
      setStableValue(committedValues);
    } catch (error) {
      // Failure: Animate back to the last stable value
      console.error("Optimistic update failed, reverting...", error);
      setInternalValue(stableValue);
    } finally {
      setIsPending(false);
    }
  };

  return (
    <SliderPrimitive.Root
      data-slot="slider"
      value={internalValue}
      onValueChange={handleValueChange}
      onValueCommit={handleValueCommit}
      min={min}
      max={max}
      className={cn(
        "relative flex w-full touch-none items-center select-none data-[disabled]:opacity-50",
        className,
      )}
      {...props}
    >
      <SliderPrimitive.Track className="bg-muted relative grow overflow-hidden rounded-full h-1.5 w-full">
        <SliderPrimitive.Range
          data-slot="slider-range"
          className={cn(
            "bg-primary absolute h-full",
            "opacity-100 brightness-125", // Visual feedback while saving
          )}
        />
        {isPending && (
          <SliderPrimitive.Range
            data-slot="slider-range"
            className={cn(
              "bg-secondary absolute h-full animate-pulse",
              "opacity-60 brightness-125", // Visual feedback while saving
            )}
          />
        )}
      </SliderPrimitive.Track>
      {internalValue.map((_, index) => (
        <SliderPrimitive.Thumb
          data-slot="slider-thumb"
          key={index}
          className={cn(
            "border-primary ring-ring/50 block size-4 shrink-0 rounded-full border bg-white shadow-sm focus-visible:ring-4 focus-visible:outline-hidden disabled:pointer-events-none",
            "scale-75 opacity-70",
          )}
        />
      ))}
    </SliderPrimitive.Root>
  );
}

export { OptimisticSlider };
