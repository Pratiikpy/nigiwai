import { Icon } from "@/components/Icon";
import type { PickerType } from "@/lib/api";
import { CATEGORIES, initials } from "@/lib/survey";

export function Tile({ name, type, className }: { name: string; type: PickerType; className?: string }) {
  const cat = CATEGORIES[type];
  return (
    <span className={`tile ${className ?? ""}`.trim()} data-cat={cat.cat} aria-hidden="true">
      {initials(name)}
      <Icon name={cat.icon} />
    </span>
  );
}
