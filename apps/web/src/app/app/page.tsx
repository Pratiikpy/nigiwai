"use client";

import Link from "next/link";
import { Icon } from "@/components/Icon";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { useSession } from "@/lib/session";
import { useVenue } from "@/lib/venue";

export default function Overview() {
  const { venue, error, canWrite } = useVenue();
  const { state } = useSession();
  const tenantName = state.status === "ready" ? state.tenant.name : "Welcome";

  if (error) return <Notice tone="error">{error}</Notice>;
  if (!venue) return <Loading label="Loading your venue…" />;

  const hasVenue = !!venue.business && !!venue.location;
  const published = venue.survey?.status === "published";
  const activeQr = venue.qrPoints.filter((q) => q.status === "active");
  const steps = [
    {
      done: hasVenue,
      title: "Describe your venue",
      detail: hasVenue ? `${venue.business?.name}, ${venue.location?.name}` : "Name, place and the nights you run shows.",
      href: "/app/venue",
      cta: hasVenue ? "Edit" : "Start",
    },
    {
      done: published,
      title: "Publish your survey",
      detail: published
        ? `Version ${venue.survey?.version} is live.`
        : "Choose what guests are asked, then publish it.",
      href: "/app/survey",
      cta: published ? "Edit" : "Set up",
    },
    {
      done: activeQr.length > 0 && published,
      title: "Put a QR poster on the counter",
      detail: activeQr.length ? `${activeQr.length} active ${activeQr.length === 1 ? "code" : "codes"}.` : "Print it and put it where guests wait.",
      href: "/app/posters",
      cta: activeQr.length ? "Manage" : "Make one",
    },
  ];
  const allDone = steps.every((s) => s.done);
  const stats = venue.stats;

  return (
    <>
      <PageHead
        title={venue.business ? venue.business.name : tenantName}
        lead={
          allDone
            ? "Your survey is live. Responses appear here as guests scan."
            : "Three steps and guests can start telling you what they love."
        }
      />

      {!venue.plan && canWrite ? (
        <section className="card onb-invite" aria-labelledby="h-onb" data-testid="invite">
          <h2 className="card__title" id="h-onb">
            Let Nigiwai get to know your business
          </h2>
          <p className="muted">
            Eight questions at most, two minutes. Nigiwai sets up your venue and chooses the tools that fit, and says why.
          </p>
          <Link className="btn btn--primary" href="/app/onboarding">
            Tell Nigiwai about your business
          </Link>
        </section>
      ) : null}

      <ol className="steps" aria-label="Set-up steps">
        {steps.map((step, i) => (
          <li key={step.title} data-done={step.done}>
            <span className="steps__n" aria-hidden="true">
              {step.done ? <Icon name="check" size="sm" /> : i + 1}
            </span>
            <span className="steps__t">
              <strong>
                {step.title}
                {step.done ? <span className="sr-only"> (done)</span> : null}
              </strong>
              <span className="meta">{step.detail}</span>
            </span>
            <Link className={`btn btn--sm${step.done ? "" : " btn--primary"}`} href={step.href}>
              {step.cta}
            </Link>
          </li>
        ))}
      </ol>

      {stats ? (
        <section aria-labelledby="h-stats" className="stack">
          <h2 id="h-stats">Responses</h2>
          <div className="stat-row">
            <div className="stat">
              <span className="stat__n" data-testid="stat-responses">
                {stats.responses}
              </span>
              <span className="meta">Counted</span>
            </div>
            <div className="stat">
              <span className="stat__n" data-testid="stat-held">
                {stats.held_for_review}
              </span>
              <span className="meta">Held for review</span>
            </div>
            <div className="stat">
              <span className="stat__n">{activeQr.length}</span>
              <span className="meta">Active QR codes</span>
            </div>
          </div>
          {stats.held_for_review > 0 ? (
            <Notice tone="warn">
              {stats.held_for_review} {stats.held_for_review === 1 ? "response was" : "responses were"} held back because{" "}
              {stats.held_for_review === 1 ? "it arrived" : "they arrived"} faster than a person can answer, or in a burst
              from one poster. They are not counted.
            </Notice>
          ) : null}
          {stats.qr_points.length ? (
            <ul className="card stack stack--sm" role="list" aria-label="Responses by poster">
              {stats.qr_points.map((p) => (
                <li key={p.id} className="row row--between">
                  <span>{p.label}</span>
                  <strong className="num">{p.responses}</strong>
                </li>
              ))}
            </ul>
          ) : null}
          <p className="meta">
            Your guests&rsquo; answers stay private. Anything that describes a group of guests will only be shown for
            groups of 10 or more.
          </p>
        </section>
      ) : null}
    </>
  );
}
