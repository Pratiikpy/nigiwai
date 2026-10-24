"use client";

import { useCallback, useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { Label } from "@/components/Label";
import { LineupStart } from "@/components/owner/LineupStart";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { ApiError, api } from "@/lib/api";
import {
  DAYS,
  PARTS,
  TRIBE_COLOURS,
  byDaypart,
  liftText,
  typeWord,
  type AudienceReading,
  type TribeCard,
  type TribeResult,
  type TribesPayload,
} from "@/lib/tribes";
import { useVenue } from "@/lib/venue";

export default function PeoplePage() {
  const { venue, error, tenantPath, canWrite } = useVenue();
  const [data, setData] = useState<TribesPayload | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const businessId = venue?.business?.id;

  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let live = true;
    if (!businessId) return;
    api<TribesPayload>(`${tenantPath}/businesses/${businessId}/tribes`)
      .then((d) => {
        if (!live) return;
        setData(d);
        setProblem(null);
      })
      .catch((e: unknown) => live && setProblem(e instanceof ApiError ? e.detail : "We couldn't load your people."));
    return () => {
      live = false;
    };
  }, [tenantPath, businessId, tick]);

  // While a refit is queued, look again every few seconds (and stop after a minute).
  const queued = data?.refit_queued ?? false;
  useEffect(() => {
    if (!queued) return;
    let tries = 0;
    const timer = setInterval(() => {
      tries += 1;
      reload();
      if (tries >= 20) clearInterval(timer);
    }, 3000);
    return () => clearInterval(timer);
  }, [queued, reload]);

  if (error) return <Notice tone="error">{error}</Notice>;
  if (!venue) return <Loading />;
  if (!venue.business) {
    return (
      <>
        <PageHead title="My people" />
        <Notice tone="warn">Set up your venue and survey first. People appear as guests answer.</Notice>
      </>
    );
  }
  if (problem) return <Notice tone="error">{problem}</Notice>;
  if (!data) return <Loading label="Reading your crowd…" />;

  const refit = async () => {
    setBusy(true);
    try {
      await api(`${tenantPath}/businesses/${venue.business?.id}/tribes/recompute`, { method: "POST" });
      reload();
    } catch (e) {
      setProblem(e instanceof ApiError ? e.detail : "We couldn't start that.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHead
        title="My people"
        lead="Groups of guests who pick alike. Each guest can sit in more than one group, so these are regions of taste, not boxes."
      />
      {data.result?.state === "provisional" || data.result?.state === "named" ? null : (
        <LineupStart tenantPath={tenantPath} businessId={venue.business.id} canWrite={canWrite} />
      )}
      <Progress data={data} />
      {data.result?.state === "unstable" ? (
        <Notice tone="warn">
          <strong>No groups shown.</strong>
          {data.result.reason} More guests, or more varied picks, can change this.
        </Notice>
      ) : null}
      {data.result?.state === "provisional" ? (
        <Notice tone="sample">
          <strong>Forming groups, provisional.</strong>
          These are early. They get names and firmer edges at {data.unlock.named} guests. The tags and items below are
          counted from real answers; the grouping itself is modelled.
        </Notice>
      ) : null}
      {data.result && (data.result.state === "provisional" || data.result.state === "named") ? (
        <div className="stack">
          {data.result.tribes.map((tribe) => (
            <TribeCardView key={tribe.index} tribe={tribe} result={data.result as TribeResult} unlockMin={data.unlock.min_group} />
          ))}
        </div>
      ) : null}
      {data.result ? <HowComputed data={data} /> : null}
      {canWrite ? (
        <div className="row row--wrap">
          <button className="btn" type="button" onClick={() => void refit()} disabled={busy || data.refit_queued}>
            <Icon name="refresh" size="sm" />
            {data.refit_queued ? "Refit queued…" : "Refit now"}
          </button>
          <span className="meta">
            The groups refit by themselves after 10 new guests, or once a day.
            {data.computed_at ? ` Last fitted ${new Date(data.computed_at).toLocaleString()}.` : ""}
          </span>
        </div>
      ) : null}
    </>
  );
}

function Progress({ data }: { data: TribesPayload }) {
  const { responses, unlock } = data;
  const usable = data.result?.n ?? 0;
  const target = responses < unlock.provisional ? unlock.provisional : unlock.named;
  const state = data.result?.state ?? "none";
  const headline =
    state === "named"
      ? "Named groups"
      : state === "provisional"
        ? "Forming groups"
        : responses === 0
          ? "No answers yet"
          : "Not enough data yet";
  return (
    <section className="card notenough" aria-labelledby="h-progress">
      <div className="row row--between row--wrap">
        <h2 className="card__title" id="h-progress">
          {headline}
        </h2>
        <Label kind="measured" detail={`${responses} ${responses === 1 ? "guest" : "guests"}`} />
      </div>
      {state === "named" ? null : (
        <div className="notenough__meter">
          <div
            className="meter"
            style={{ "--v": Math.min(responses, target), "--max": target } as React.CSSProperties}
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={target}
            aria-valuenow={Math.min(responses, target)}
            aria-label="Guests so far"
          />
          <span className="notenough__n">
            {responses} of {target}
          </span>
        </div>
      )}
      <p className="meta">
        {responses < unlock.provisional
          ? `Groups start to form from ${unlock.provisional} guests and get names at ${unlock.named}. Below that, a few picks say too little to tell groups apart honestly.`
          : state === "named"
            ? `${usable} guests with usable picks are in these groups.`
            : `Names unlock at ${unlock.named} guests.`}
        {data.result && usable < responses
          ? ` ${responses - usable} ${responses - usable === 1 ? "guest" : "guests"} had too few picks that Qloo could describe and ${responses - usable === 1 ? "is" : "are"} left out.`
          : ""}
      </p>
    </section>
  );
}

function TribeCardView({ tribe, result, unlockMin }: { tribe: TribeCard; result: TribeResult; unlockMin: number }) {
  const colour = TRIBE_COLOURS[tribe.index % TRIBE_COLOURS.length];
  const named = result.state === "named";
  if (!tribe.shown) {
    return (
      <article className="card" style={{ ["--c" as string]: colour }} aria-label={`${tribe.label}, withheld`}>
        <h2 className="tribe">
          <span className="tribe__dot" aria-hidden="true" />
          {tribe.label}
        </h2>
        <p className="meta">
          This group has fewer than {unlockMin} guests, so nothing about it is shown. Nothing here describes a smaller group.
        </p>
      </article>
    );
  }
  return (
    <article className="card tribe-card" style={{ ["--c" as string]: colour }} aria-labelledby={`t-${tribe.index}`}>
      <header className="stack stack--sm">
        <div className="row row--between row--wrap">
          <h2 className="tribe" id={`t-${tribe.index}`}>
            <span className="tribe__dot" aria-hidden="true" />
            {tribe.label}
            {!named ? <span className="pill" data-tone="warn">Provisional</span> : null}
          </h2>
          <div className="lbl-set">
            <Label kind="measured" detail={`about ${Math.round(tribe.soft_size)} guests`} />
            <Label kind="modelled" detail="grouping" />
          </div>
        </div>
        {tribe.line ? <p className="muted">{tribe.line}</p> : null}
        <div
          className="tribebar"
          role="img"
          aria-label={`${Math.round(tribe.share * 100)} percent of your guests, counting each guest by how much they belong`}
        >
          <span style={{ ["--w" as string]: `${Math.max(tribe.share * 100, 1)}%`, ["--c" as string]: colour }} />
        </div>
        <p className="meta">
          About {Math.round(tribe.share * 100)}% of your guests, counting each by how much they belong to this group.
        </p>
      </header>

      <div className="grid-2">
        <div className="stack stack--sm">
          <h3 className="eyebrow" id={`tg-${tribe.index}`}>
            What they over-index on
          </h3>
          {tribe.top_tags.length ? (
            <ul className="legend-list" role="list">
              {tribe.top_tags.slice(0, 6).map((t) => (
                <li key={t.tag_id}>
                  <span aria-hidden="true" />
                  <span>
                    {t.name}
                    <span className="meta"> · {t.support} items</span>
                  </span>
                  <span className="num" title="How much more often this group's picks carry the tag than your whole crowd's, with a 90% interval">
                    {liftText(t)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="meta">No tag stands out clearly enough yet.</p>
          )}
          <p className="meta">Higher than 1× means more than the crowd as a whole. The interval is 90%, from resampling your guests.</p>
        </div>

        <div className="stack stack--sm">
          <h3 className="eyebrow" id={`ti-${tribe.index}`}>
            Most picked
          </h3>
          <ul className="legend-list" role="list">
            {tribe.top_items.slice(0, 6).map((i) => (
              <li key={i.entity_id}>
                <span aria-hidden="true" />
                <span>
                  {i.name}
                  <span className="meta"> · {typeWord(i.type)}</span>
                </span>
                <span className="num">{Math.round(i.weight * 10) / 10}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <Rhythm tribe={tribe} />

      <p className="meta" data-testid={`reproducibility-${tribe.index}`}>
        Tested on a crowd of {result.n}.
        {tribe.tag_overlap != null
          ? ` Its leading tags overlap ${Math.round(tribe.tag_overlap * 100)}% when the guests are resampled.`
          : ""}
        {result.stability ? ` The crowd’s stability beyond chance is ${result.stability.corrected.toFixed(2)}.` : ""}
      </p>

      <Audience tribe={tribe} reading={result.audience?.[String(tribe.index)]} />

      {tribe.signatures.length ? (
        <div className="stack stack--sm">
          <h3 className="eyebrow" id={`ts-${tribe.index}`}>
            What they combine
          </h3>
          <ul className="stack stack--sm" role="list">
            {tribe.signatures.slice(0, 3).map((s) => (
              <li key={s.types.join("+")}>
                {typeWord(s.types[0])} and {typeWord(s.types[1])}: {Math.round(s.tribe_share * 100)}% of this group, against{" "}
                {Math.round(s.crowd_share * 100)}% of all guests.{" "}
                <span className="meta">
                  {s.odd
                    ? `An unusual pairing (group of about ${Math.round(s.group_size)}).`
                    : `Descriptive only: the group is under 200, so this may just mirror its main interest.`}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </article>
  );
}

function Audience({ tribe, reading }: { tribe: TribeCard; reading: AudienceReading | undefined }) {
  if (!reading) return null;
  return (
    <div className="stack stack--sm" data-testid={`audience-${tribe.index}`}>
      <div className="row row--between row--wrap">
        <h3 className="eyebrow" id={`ta-${tribe.index}`}>
          Who they tend to be
        </h3>
        <Label kind="modelled" detail="from Qloo’s audience data" />
      </div>
      {reading.status === "ok" ? (
        <>
          <p>
            <strong>{reading.age.label}</strong> · <strong>{reading.gender.label}</strong>
          </p>
          <p className="meta">
            Read from Qloo’s audience data for the {reading.items_used} items this group picks most, compared with Qloo’s
            average audience. Your guests were never asked their age or gender, and the accuracy of this reading is not verified.
          </p>
        </>
      ) : (
        <p className="meta">{reading.reason}</p>
      )}
    </div>
  );
}

function Rhythm({ tribe }: { tribe: TribeCard }) {
  const grid = byDaypart(tribe.rhythm);
  const max = Math.max(...grid.flat(), 0.0001);
  const total = grid.flat().reduce((a, b) => a + b, 0);
  return (
    <div className="stack stack--sm">
      <div className="row row--between row--wrap">
        <h3 className="eyebrow" id={`tr-${tribe.index}`}>
          When they come
        </h3>
        <Label kind="measured" detail={`${Math.round(total)} scans`} />
      </div>
      <table className="rhythm">
        <caption className="sr-only">Guests of this group by weekday and part of the day, in your local time</caption>
        <thead>
          <tr>
            <td className="rhythm__corner" />
            {PARTS.map((p) => (
              <th key={p.label} scope="col">
                {p.label}
                <span className="meta"> {p.hint}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {DAYS.map((day, d) => (
            <tr key={day}>
              <th scope="row">{day}</th>
              {grid[d]?.map((v, p) => (
                <td key={PARTS[p]?.label} style={{ ["--v" as string]: v / max }}>
                  {v >= 0.5 ? Math.round(v * 10) / 10 : ""}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HowComputed({ data }: { data: TribesPayload }) {
  const r = data.result;
  if (!r) return null;
  const s = r.stability;
  return (
    <details className="disc card card--flat">
      <summary className="row row--between">
        <span className="card__title">How this was computed</span>
        <Icon name="chev-r" />
      </summary>
      <div className="disc__body">
        <p>
          Each guest becomes a row of the tags Qloo attaches to what they picked (facility and country tags are dropped).
          A soft factor model finds {r.k} groups; every guest gets a share in each. Version {r.version}, fitted on{" "}
          {r.n} guests and {r.vocab_size} tags. Fingerprint <span className="mono">{r.input_hash.slice(0, 12)}</span>.
        </p>
        {s ? (
          <dl className="parts">
            <div>
              <dt>Stability of these groups</dt>
              <dd>{s.raw.toFixed(2)}</dd>
              <p className="parts__why">
                How often refitting on a resampled crowd puts the same guests together (1 is perfect). Resampled {s.bootstrap} times.
              </p>
            </div>
            <div>
              <dt>Same crowd with its tags shuffled</dt>
              <dd>{s.null_permuted.toFixed(2)}</dd>
              <p className="parts__why">Structure destroyed. The real crowd beat {s.null_runs - Math.round((s.p_permuted * (s.null_runs + 1)) - 1)} of {s.null_runs} such draws.</p>
            </div>
            <div>
              <dt>Same number of random popular picks</dt>
              <dd>{s.null_random_picks.toFixed(2)}</dd>
              <p className="parts__why">Popularity without taste. The real crowd beat {s.null_runs - Math.round((s.p_random_picks * (s.null_runs + 1)) - 1)} of {s.null_runs} such draws.</p>
            </div>
            <div>
              <dt>Stability beyond chance</dt>
              <dd>{s.corrected.toFixed(2)}</dd>
              <p className="parts__why">The stability above minus the larger of the two shuffled versions.</p>
            </div>
            <div>
              <dt>Groups shown only if they beat both</dt>
              <dd>{s.beats_both_nulls ? "yes" : "no"}</dd>
              <p className="parts__why">One-sided p-values {s.p_permuted.toFixed(2)} and {s.p_random_picks.toFixed(2)}, shown if both are at most 0.05.</p>
            </div>
          </dl>
        ) : null}
        <p className="meta">
          Tags come from items Qloo returned for your guests&rsquo; picks. Group names use the tags a group over-indexes
          on; nothing is invented. Thresholds (60 and 200 guests) come from stability tests on a public listening data
          set and on Qloo tags; whether groups predict anything for your venue is not yet tested.
        </p>
      </div>
    </details>
  );
}
