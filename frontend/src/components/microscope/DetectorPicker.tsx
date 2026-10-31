import { useDetectorState } from "@/apps/default/hooks/states";
import { Button } from "@/components/ui/button";

/**
 * Which detectors image a stream: every one picked becomes channels of the dataset, a color camera
 * one per color.
 */
export function DetectorPicker({
  value,
  onChange,
  size = "sm",
}: {
  value: string[];
  onChange: (detectors: string[]) => void;
  size?: "sm" | "xs";
}) {
  const { data: detectorState } = useDetectorState({ subscribe: true });
  const detectors = detectorState?.detectors ?? [];
  const toggle = (name: string) =>
    onChange(
      value.includes(name)
        ? value.filter((picked) => picked !== name)
        : [...value, name],
    );

  return (
    <div className="flex flex-wrap gap-1">
      {detectors.map((detector) => (
        <Button
          key={detector.name}
          type="button"
          variant={value.includes(detector.name) ? "default" : "outline"}
          aria-pressed={value.includes(detector.name)}
          className={
            size === "xs" ? "h-6 px-1.5 text-[10px]" : "h-8 px-2 text-xs"
          }
          onClick={() => toggle(detector.name)}
        >
          {detector.name}
          {detector.colors.length > 0 && ` (${detector.colors.join("")})`}
        </Button>
      ))}
    </div>
  );
}
