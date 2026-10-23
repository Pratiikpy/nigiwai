"use client";

import { useSyncExternalStore } from "react";
import { Icon } from "./Icon";

const subscribe = (notify: () => void) => {
  const observer = new MutationObserver(notify);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => observer.disconnect();
};
const read = () => (document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light");

/** Light or dark. The choice is remembered in this browser only; with no choice the system setting applies. */
export function ThemeToggle() {
  const theme = useSyncExternalStore(subscribe, read, () => "light");
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      className="btn btn--sm btn--ghost"
      type="button"
      onClick={() => {
        document.documentElement.setAttribute("data-theme", next);
        try {
          localStorage.setItem("nigiwai-theme", next);
        } catch {
          /* private windows: the choice lasts for this page only */
        }
      }}
      aria-label={`Switch to ${next} theme`}
    >
      <Icon name={theme === "dark" ? "sun" : "moon"} size="sm" />
      {theme === "dark" ? "Light" : "Dark"}
    </button>
  );
}
