import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { useElementStore } from "@/store/elementStore";
import { useModeStore } from "@/store/modeStore";

const Rows = ({ rows }: { rows: Record<string, string> }) => (
  <dl className="space-y-1">
    {Object.entries(rows).map(([label, value]) => (
      <div key={label} className="flex justify-between gap-4">
        <dt className="text-muted-foreground">{label}</dt>
        <dd className="text-right font-medium">{value}</dd>
      </div>
    ))}
  </dl>
);

/** What the selected element on a light path is made of, and what it is set to. */
export const ElementPanel = () => {
  const element = useElementStore((s) => s.selectedElement);
  const displayMode = useModeStore((s) => s.displayMode);

  if (displayMode !== "3D" || !element) return null;

  const set = Object.keys(element.values).length > 0;
  return (
    <Card className="absolute right-3 top-3 z-20 w-64 space-y-2 p-4 text-xs shadow-2xl backdrop-blur-md">
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold">{element.label}</span>
        <Badge variant="outline" className="font-normal">
          {element.kind}
        </Badge>
      </div>
      <Rows rows={element.facts} />
      {set && <Separator />}
      {set && <Rows rows={element.values} />}
    </Card>
  );
};
