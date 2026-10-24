"use client";

import { Icon } from "@/components/Icon";

export function Notice({ tone, children }: { tone: "ok" | "warn" | "error" | "sample"; children: React.ReactNode }) {
  return (
    <div className="banner" data-tone={tone} role={tone === "error" ? "alert" : "status"}>
      <Icon name={tone === "ok" ? "check" : tone === "sample" ? "info" : "alert"} />
      <div className="banner__body">{children}</div>
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="res-status" role="status">
      <span className="spin" aria-hidden="true" />
      {label}
    </div>
  );
}

export function PageHead({ title, lead, children, as: Tag = "h1" }: { title: string; lead?: string; children?: React.ReactNode; as?: "h1" | "h2" }) {
  return (
    <div className="page-h">
      <Tag className="display">{title}</Tag>
      {lead ? <p className="muted">{lead}</p> : null}
      {children}
    </div>
  );
}
