import type { Metadata } from "next";
import evidence from "@/content/evidence.json";

export const metadata: Metadata = {
  title: "Evidence",
  description: "Our own tests of what Qloo adds, including the ones it lost.",
};

type Verdict = "win" | "tie" | "loss" | "open";
const WORD: Record<Verdict, string> = { win: "Won", tie: "Tied", loss: "Lost", open: "Open" };

function VerdictMark({ v }: { v: Verdict }) {
  return (
    <span className="verdict" data-v={v}>
      {WORD[v]}
    </span>
  );
}

export default function EvidencePage() {
  const tally = (v: Verdict) => evidence.proofs.filter((p) => p.verdict === v).length;
  return (
    <>
      <section className="hero" aria-labelledby="h-ev">
        <p className="eyebrow">Evidence</p>
        <h1 id="h-ev">What we tested, including what Qloo lost.</h1>
        <p>{evidence.intro}</p>
      </section>

      <section className="card tally" aria-label="Tally of our research tests" data-testid="tally">
        {(["win", "tie", "loss", "open"] as const).map((v) => (
          <div key={v}>
            <strong>{tally(v)}</strong>
            <span>{WORD[v]}</span>
          </div>
        ))}
        <p className="meta">Of {evidence.proofs.length} research tests, updated {evidence.updated}. Each is also listed below with how it was run and what it does not show.</p>
      </section>

      <section className="proofs" aria-label="Research tests">
        {evidence.proofs.map((p) => (
          <article className="card proof" key={p.id} data-testid="proof" id={`proof-${p.id}`}>
            <div>
              <p className="eyebrow">Test {p.id}</p>
              <h2 className="proof__t">{p.title}</h2>
              <p className="meta">{p.method}</p>
            </div>
            <div>
              <p>{p.result}</p>
              <p className="meta">{p.verdict_text}</p>
            </div>
            <VerdictMark v={p.verdict as Verdict} />
            <p className="limits">
              <strong>Limits.</strong> {p.limits}
            </p>
          </article>
        ))}
      </section>

      <section aria-labelledby="h-bd" className="stack">
        <h2 id="h-bd">Checks on the product itself</h2>
        <div className="proofs">
          {evidence.build.map((b) => (
            <article className="card proof" key={b.title}>
              <div>
                <h3 className="proof__t">{b.title}</h3>
              </div>
              <div>
                <p>{b.result}</p>
              </div>
              <VerdictMark v={b.verdict as Verdict} />
            </article>
          ))}
        </div>
      </section>

      <section className="card" aria-labelledby="h-rd">
        <h2 className="card__title" id="h-rd">
          How to read it
        </h2>
        <p>{evidence.reading}</p>
        <p className="meta">
          This page holds our own aggregate results only: no Qloo response data is published, because Qloo&rsquo;s terms do not allow it. Every figure is a result we measured; anything we did not measure
          is said to be untested.
        </p>
      </section>
    </>
  );
}
