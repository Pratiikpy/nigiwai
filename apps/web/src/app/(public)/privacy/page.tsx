import type { Metadata } from "next";
import { Icon } from "@/components/Icon";
import privacy from "@/content/privacy.json";

export const metadata: Metadata = {
  title: "Privacy",
  description: "What a guest gives, what is never collected, and the rules the product follows.",
};

export default function PrivacyPage() {
  return (
    <>
      <section className="hero" aria-labelledby="h-pv">
        <p className="eyebrow">Privacy</p>
        <h1 id="h-pv">A crowd has a buzz. A person is never singled out.</h1>
        <p>Nigiwai describes groups of people who like similar things. It never describes, scores or identifies one person.</p>
      </section>

      <div className="two">
        <section className="card" aria-labelledby="h-col">
          <h2 className="card__title" id="h-col" style={{ marginBottom: "var(--s-3)" }}>
            What is stored for each answer
          </h2>
          <ul className="ticks" data-testid="stored">
            {privacy.stored_per_answer.map((s) => (
              <li key={s.what}>
                <Icon name="check" />
                {s.what}.
              </li>
            ))}
          </ul>
        </section>
        <section className="card" aria-labelledby="h-not">
          <h2 className="card__title" id="h-not" style={{ marginBottom: "var(--s-3)" }}>
            What is never collected
          </h2>
          <ul className="ticks" data-testid="never">
            {privacy.never.map((x) => (
              <li key={x}>
                <Icon name="nouser" />
                {x}
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section className="card" aria-labelledby="h-rules">
        <h2 className="card__title" id="h-rules" style={{ marginBottom: "var(--s-3)" }}>
          The rules the product follows
        </h2>
        <ul className="ticks">
          {privacy.rules.map((x) => (
            <li key={x}>
              <Icon name="shield" />
              {x}
            </li>
          ))}
        </ul>
      </section>

      <section className="card" aria-labelledby="h-wl">
        <h2 className="card__title" id="h-wl" style={{ marginBottom: "var(--s-3)" }}>
          Separate from the guest survey: the owner waitlist
        </h2>
        <p>
          If an owner joins the waitlist we keep their email address and the version of the consent text they saw. It is stored in its own table, apart from any survey data, and is never joined to it.
        </p>
        <p className="meta">
          Owners who feed back with &ldquo;Was this useful?&rdquo; send a yes or no and an optional line of text. It is stored without the account, the venue or anything that identifies who sent it.
        </p>
      </section>
      <p className="meta">This page is checked against the database: a test fails if a column holding guest data is added without being listed here. Last updated {privacy.updated}.</p>
    </>
  );
}
