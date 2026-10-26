import type { Metadata } from "next";
import { Icon } from "@/components/Icon";
import { Label } from "@/components/Label";
import { Waitlist } from "./Waitlist";

export const metadata: Metadata = {
  title: "Business case",
  description: "Who Nigiwai is for, what an owner gets, and what we have not yet tested.",
};

const RINGS = [
  { n: "1", who: "Independent live-music venues and bars that book acts.", size: "About 3,000 independent venues were reported in 2021 (Pollstar); old, and venues only." },
  { n: "2", who: "Restaurants, breweries, hotel bars, festivals and promoters that book acts.", size: "The same flow, no new feature." },
  {
    n: "2b",
    who: "Every room with a speaker: the Sound plan.",
    size: "More than 1 million US restaurant locations (National Restaurant Association, 2025); about 70,000 US bars and nightclubs (IBISWorld, 2026).",
  },
  { n: "3", who: "Artists and managers choosing rooms; brands booking talent.", size: "Later. Needs venue data and a commercial agreement with Qloo." },
];

export default function BusinessPage() {
  return (
    <>
      <section className="hero" aria-labelledby="h-bz">
        <p className="eyebrow">Business case</p>
        <h1 id="h-bz">One question, answered for every room that books or plays music.</h1>
        <p>Who is actually in my room, and what should I book or play for them?</p>
      </section>

      <div className="two">
        <section className="card">
          <h2 className="card__title" style={{ marginBottom: "var(--s-3)" }}>
            The problem
          </h2>
          <ul className="ticks">
            {[
              "Quiet weeknights and bookings chosen on gut feel.",
              "Existing tools handle logistics or audience marketing, not “does this act fit the crowd I have”.",
              "Background music is picked by business type and mood, not by who is there.",
              "Tickets and tabs say how many came, not who they were.",
              "A booker's pitch says what an act has done elsewhere, not what this room's regulars like.",
            ].map((t) => (
              <li key={t}>
                <Icon name="alert" />
                {t}
              </li>
            ))}
          </ul>
        </section>
        <section className="card">
          <h2 className="card__title" style={{ marginBottom: "var(--s-3)" }}>
            What an owner gets
          </h2>
          <ul className="ticks">
            {[
              "A map of their crowd and its groups.",
              "A Soundcheck for any act, with the working shown.",
              "A one-page Booking Brief to forward to a booker.",
              "A Today board: their quietest hours, from their own scans, and what to try about them.",
              "A Sound plan: which acts to play at which time of the week.",
              "Grow: tastes that sit next to their groups and are missing from their crowd, and the places Qloo ties to it, each with the check that decided what it may claim.",
              "Moves: log a change and see whether scans in that slot moved, with the doubt shown.",
              "Drafts for an enquiry, an event page, a post or an ad angle, filled from their own records and never sent for them.",
            ].map((t) => (
              <li key={t}>
                <Icon name="check" />
                {t}
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section className="card" aria-labelledby="h-rg">
        <h2 className="card__title" id="h-rg" style={{ marginBottom: "var(--s-3)" }}>
          Who it is for
        </h2>
        <div className="rings">
          {RINGS.map((r) => (
            <div className="ringrow" key={r.n}>
              <span className="rn">{r.n}</span>
              <div>
                <strong>{r.who}</strong>
                <p className="meta">{r.size}</p>
              </div>
            </div>
          ))}
        </div>
        <p className="meta" style={{ marginTop: "var(--s-4)" }}>
          Size figures are outside estimates and not verified as current. No revenue claim is made.
        </p>
      </section>

      <div className="two">
        <section className="card">
          <h2 className="card__title" style={{ marginBottom: "var(--s-3)" }}>
            Price
          </h2>
          <p style={{ marginBottom: "var(--s-3)" }}>
            A subscription per venue. The price is a hypothesis we have not tested, so none is shown. A free tier would cover a first crowd map.
          </p>
          <Label kind="modelled" detail="not yet tested" />
        </section>
        <section className="card">
          <h2 className="card__title" style={{ marginBottom: "var(--s-3)" }}>
            Join the waitlist
          </h2>
          <Waitlist />
        </section>
      </div>
    </>
  );
}
