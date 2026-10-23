import type { SVGProps } from "react";

export type IconName =
  | "search" | "x" | "plus" | "minus" | "check" | "chev-r" | "chev-d" | "chev-l" | "arrow-r" | "lock" | "shield"
  | "info" | "alert" | "refresh" | "share" | "copy" | "map" | "sun" | "moon" | "chat" | "people" | "layers" | "clock"
  | "calendar" | "music" | "screen" | "film" | "tag" | "pin" | "book" | "qr" | "trash" | "sliders" | "ext"
  | "download" | "send" | "list" | "flag" | "hex" | "compare" | "menu" | "nouser" | "table" | "pause" | "bolt"
  | "gift" | "mic" | "gamepad";

type Props = { name: IconName; size?: "sm" | "lg" } & Omit<SVGProps<SVGSVGElement>, "name">;

/** One icon from the sprite in the root layout. Decorative: pair it with visible text or an aria-label on the control. */
export function Icon({ name, size, className, ...rest }: Props) {
  const cls = ["ic", size ? `ic--${size}` : "", className ?? ""].filter(Boolean).join(" ");
  return (
    <svg className={cls} aria-hidden="true" focusable="false" {...rest}>
      <use href={`#i-${name}`} />
    </svg>
  );
}
