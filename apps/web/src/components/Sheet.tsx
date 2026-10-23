"use client";

import { useEffect, useId, useRef } from "react";
import { Icon } from "./Icon";

type Props = {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  /** `alertdialog` for confirmations that need an explicit answer. */
  role?: "dialog" | "alertdialog";
  hideClose?: boolean;
  children: React.ReactNode;
};

/**
 * A bottom sheet inside the phone frame. While open it takes focus, closes on Escape and returns focus to
 * whatever opened it. The page behind it is made inert by the parent (see `inert` on the survey regions).
 */
export function Sheet({ open, onClose, title, subtitle, role = "dialog", hideClose, children }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const idBase = useId();

  useEffect(() => {
    if (!open) return;
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const timer = setTimeout(() => {
      const target = ref.current?.querySelector<HTMLElement>("input, button, [href], textarea");
      (target ?? ref.current)?.focus({ preventScroll: true });
    }, 30);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "Tab" && ref.current) {
        const items = Array.from(
          ref.current.querySelectorAll<HTMLElement>("button:not([disabled]), [href], input:not([disabled]), textarea"),
        );
        const first = items[0];
        const last = items[items.length - 1];
        if (!first || !last) return;
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("keydown", onKey);
      const back = opener.current;
      if (back && document.contains(back)) back.focus({ preventScroll: true });
    };
  }, [open, onClose]);

  return (
    <>
      <div className={`scrim${open ? " is-open" : ""}`} onClick={onClose} aria-hidden="true" />
      <div
        ref={ref}
        className={`sheet${open ? " is-open" : ""}`}
        role={role}
        aria-modal="true"
        aria-labelledby={`${idBase}-h`}
        tabIndex={-1}
        inert={!open}
      >
        <div className="sheet__grip" aria-hidden="true" />
        <div className="sheet__head">
          <div>
            <h2 className="card__title" id={`${idBase}-h`}>
              {title}
            </h2>
            {subtitle ? <p className="meta">{subtitle}</p> : null}
          </div>
          {hideClose ? null : (
            <button className="iconbtn" type="button" onClick={onClose} aria-label="Close">
              <Icon name="x" />
            </button>
          )}
        </div>
        <div className="sheet__body">{children}</div>
      </div>
    </>
  );
}
