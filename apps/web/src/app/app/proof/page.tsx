"use client";

import { useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { Label } from "@/components/Label";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { ApiError, api } from "@/lib/api";
import { useVenue } from "@/lib/venue";

type Call = {
  id: string;
  at: string;
  purpose: string;
  endpoint: string;
  params: [string, string][];
  status: string;
  http_status: number | null;
  transport: string;
  cache: string;
  latency_ms: number;
  results: number;
  rules: { rule: string; effect: string; detail: string }[];
};
type Proof = {
  integrity: { items_shown: number; items_traced: number; invented: number; rule: string };
  usage_30_days: {
    calls: number;
    cached: number;
    cache_share: number | null;
    by_purpose: { purpose: string; calls: number; live: number; cached: number; problems: number; avg_live_ms: number | null }[];
  };
  recent_calls: Call[];
  hidden: string;
};

const PURPOSE: Record<string, string> = {
  picker: "Guests searching",
  card: "Guests’ Taste Cards",
  tribes: "Reading tags and audiences for your groups",
  lineup: "Matching public lineups",
  ask: "Ask Nigiwai",
  fit: "Fit checks",
  board: "Boards",
};

export default function ProofPage() {
  const { tenantPath } = useVenue();
  const [data, setData] = useState<Proof | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api<Proof>(`${tenantPath}/proof`)
      .then((d) => live && setData(d))
      .catch((e: unknown) => live && setProblem(e instanceof ApiError ? e.detail : "We couldn’t load this."));
    return () => {
      live = false;
    };
  }, [tenantPath]);

  if (problem) return <Notice tone="error">{problem}</Notice>;
  if (!data) return <Loading />;
  const i = data.integrity;

  return (
    <>
      <PageHead
        title="Proof"
        lead="What Qloo was asked on your behalf, how it answered, and whether anything you are shown can be traced back to it."
      />

      <section className="card stack" aria-labelledby="h-int" data-testid="integrity">
        <div className="row row--between row--wrap">
          <h2 className="card__title" id="h-int">
            Invented items
          </h2>
          <Label kind="observed" detail="checked against what Qloo returned" />
        </div>
        <p className="fit__n" style={{ fontSize: "var(--t-4xl)" }} data-testid="invented-count">
          {i.invented}
          <span className="fit__of"> of {i.items_shown} items shown</span>
        </p>
        {i.invented === 0 ? (
          <Notice tone="ok">
            {i.items_shown === 0
              ? "Nothing has been shown yet, so there is nothing to check."
              : `All ${i.items_traced} items on your groups and public-lineup views are entities Qloo returned.`}
          </Notice>
        ) : (
          <Notice tone="error">
            {i.invented} {i.invented === 1 ? "item" : "items"} could not be traced to a Qloo answer. That should never
            happen: tell us.
          </Notice>
        )}
        <p className="meta">{i.rule}</p>
      </section>

      <section className="card stack" aria-labelledby="h-use">
        <div className="row row--between row--wrap">
          <h2 className="card__title" id="h-use">
            Qloo use, last 30 days
          </h2>
          <Label kind="measured" detail={`${data.usage_30_days.calls} calls`} />
        </div>
        {data.usage_30_days.calls === 0 ? (
          <p className="muted">No calls yet.</p>
        ) : (
          <>
            <p className="muted">
              {Math.round((data.usage_30_days.cache_share ?? 0) * 100)}% of calls were answered from the private cache and
              did not reach Qloo.
            </p>
            <table className="rhythm" style={{ tableLayout: "auto" }}>
              <caption className="sr-only">Qloo calls by purpose in the last 30 days</caption>
              <thead>
                <tr>
                  <th scope="col">What for</th>
                  <th scope="col">Calls</th>
                  <th scope="col">To Qloo</th>
                  <th scope="col">Cached</th>
                  <th scope="col">Problems</th>
                  <th scope="col">Typical wait</th>
                </tr>
              </thead>
              <tbody>
                {data.usage_30_days.by_purpose.map((p) => (
                  <tr key={p.purpose}>
                    <th scope="row">{PURPOSE[p.purpose] ?? p.purpose}</th>
                    <td className="num">{p.calls}</td>
                    <td className="num">{p.live}</td>
                    <td className="num">{p.cached}</td>
                    <td className="num">{p.problems}</td>
                    <td className="num">{p.avg_live_ms != null ? `${(p.avg_live_ms / 1000).toFixed(1)} s` : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
        <p className="meta">{data.hidden}</p>
      </section>

      <section className="stack" aria-labelledby="h-calls">
        <h2 id="h-calls">Recent calls</h2>
        {data.recent_calls.length === 0 ? (
          <p className="muted">
            Calls made for your groups and public lineups will be listed here, with what was sent and what came back.
          </p>
        ) : (
          <ul className="stack stack--sm" role="list">
            {data.recent_calls.map((c) => (
              <li key={c.id}>
                <details className="disc card card--flat">
                  <summary className="row row--between">
                    <span>
                      <strong>{PURPOSE[c.purpose] ?? c.purpose}</strong>{" "}
                      <span className="meta">
                        {c.endpoint} · {c.results} {c.results === 1 ? "result" : "results"} ·{" "}
                        {c.cache === "miss" ? `${c.latency_ms} ms` : "from cache"} · {new Date(c.at).toLocaleString()}
                      </span>
                    </span>
                    <Icon name="chev-r" />
                  </summary>
                  <div className="disc__body">
                    <dl className="parts">
                      <div>
                        <dt>Answer</dt>
                        <dd>
                          {c.status}
                          {c.http_status ? ` (HTTP ${c.http_status})` : ""} via {c.transport}
                        </dd>
                      </div>
                      <div>
                        <dt>Sent</dt>
                        <dd className="mono" style={{ overflowWrap: "anywhere", textAlign: "left" }}>
                          {c.params.map(([k, v]) => `${k}=${v}`).join("  ")}
                        </dd>
                      </div>
                    </dl>
                    {c.rules.length ? (
                      <ul className="stack stack--sm" role="list" aria-label="Rules that changed the answer">
                        {c.rules.map((r, k) => (
                          <li key={k}>
                            <span className="mono">{r.rule}</span> {r.effect}: {r.detail}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="meta">No rule changed this answer.</p>
                    )}
                  </div>
                </details>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
