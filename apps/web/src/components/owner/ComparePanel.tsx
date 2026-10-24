"use client";

import { useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { Label } from "@/components/Label";
import { ApiError, api } from "@/lib/api";
import { Loading, Notice } from "./ui";

type Item = { name: string; entity_id: string };
type AiItem = { name: string; verified: boolean; entity_id: string | null; in_qloo_list: boolean };
export type Comparison = {
  question: string;
  qloo: { available: boolean; reason: string | null; items: Item[] };
  ai: { available: boolean; reason: string | null; model: string | null; recognised: boolean | null; items: AiItem[] };
  summary: string;
};

function Mark({ ok }: { ok: boolean }) {
  return ok ? (
    <span className="vmark" title="Resolved to a real Qloo entity">
      <Icon name="check" />
      <span className="sr-only">In Qloo</span>
      <span aria-hidden="true">In Qloo</span>
    </span>
  ) : (
    <span className="meta" style={{ marginLeft: "auto", whiteSpace: "nowrap" }}>
      not found in Qloo
    </span>
  );
}

/**
 * Qloo against an AI alone (M23): the same question put to both, side by side. Neither side is ranked above the
 * other; the marks show which acts resolve to a real Qloo entity, and a model that does not know an act says so.
 */
export function ComparePanel({ base, soundcheckId, name }: { base: string; soundcheckId: string; name: string }) {
  const [data, setData] = useState<Comparison | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api<Comparison>(`${base}/soundchecks/${soundcheckId}/compare`)
      .then((d) => live && setData(d))
      .catch((e: unknown) => live && setProblem(e instanceof ApiError ? e.detail : "We couldn’t load the comparison."));
    return () => {
      live = false;
    };
  }, [base, soundcheckId]);

  return (
    <aside className="card cmp" aria-labelledby="h-cmp" data-testid="compare">
      <div className="card__head" style={{ marginBottom: 0 }}>
        <h2 className="card__title" id="h-cmp">
          Qloo and an AI alone
        </h2>
        <Label kind="observed" />
      </div>
      {problem ? <Notice tone="error">{problem}</Notice> : null}
      {!data && !problem ? <Loading label={`Asking both about ${name}…`} /> : null}
      {data ? (
        <>
          <p className="cmp__sum" data-testid="compare-summary">
            {data.summary}
          </p>
          <div className="cmp__cols">
            <div className="cmp__col">
              <h3>
                Qloo<small>its graph, checked items</small>
              </h3>
              {data.qloo.available ? (
                <ol>
                  {data.qloo.items.map((i, n) => (
                    <li key={i.entity_id} className={data.ai.items.some((a) => a.entity_id === i.entity_id) ? "same" : ""}>
                      <span className="n">{n + 1}</span>
                      <span>{i.name}</span>
                      <Mark ok />
                    </li>
                  ))}
                </ol>
              ) : (
                <ol>
                  <li className="unk">
                    <span>{data.qloo.reason ?? "Qloo did not answer."}</span>
                  </li>
                </ol>
              )}
            </div>
            <div className="cmp__col">
              <h3>
                AI alone<small>no tools, no Qloo data</small>
              </h3>
              <ol>
                {!data.ai.available ? (
                  <li className="unk" data-testid="ai-unavailable">
                    <span>No AI answer: {data.ai.reason}</span>
                  </li>
                ) : data.ai.recognised === false ? (
                  <li className="unk">
                    <span>The AI alone said it does not know this act, and gave no list.</span>
                  </li>
                ) : (
                  data.ai.items.map((i, n) => (
                    <li key={i.name} className={i.in_qloo_list ? "same" : ""}>
                      <span className="n">{n + 1}</span>
                      <span>{i.name}</span>
                      <Mark ok={i.verified} />
                    </li>
                  ))
                )}
              </ol>
            </div>
          </div>
          <p className="cmp__note">
            <Icon name="check" size="sm" /> means the act resolved to a real Qloo entity. Ties are shown as ties. On famous acts an AI alone often matches
            Qloo; the difference shows on small acts and on checking that an act is real.
            {data.ai.model ? ` AI answers are from ${data.ai.model}.` : ""}
          </p>
        </>
      ) : null}
    </aside>
  );
}
