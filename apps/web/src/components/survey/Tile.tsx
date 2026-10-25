import { Icon } from "@/components/Icon";
import type { PickerType } from "@/lib/api";
import { CATEGORIES, initials } from "@/lib/survey";

export function Tile({ name, type, className }: { name: string; type: PickerType; className?: string }) {
  const cat = CATEGORIES[type];
  return (
    // The initials are drawn by CSS from `data-initials`, not written as text: they are decoration for the eye, and text inside a button
    // that its accessible name does not contain (WCAG 2.5.3, Label in Name) is a defect even when it is hidden from a screen reader.
    <span className={`tile ${className ?? ""}`.trim()} data-cat={cat.cat} data-initials={initials(name)} aria-hidden="true">
      <Icon name={cat.icon} />
    </span>
  );
}
