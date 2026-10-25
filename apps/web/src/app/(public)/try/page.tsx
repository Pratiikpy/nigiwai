import type { Metadata } from "next";
import { DemoVenues } from "@/components/DemoVenues";
import { FindVenue } from "@/components/FindVenue";
import { Icon } from "@/components/Icon";

export const metadata: Metadata = {
  title: "Try a venue",
  description: "Open a real venue read from its public lineups and soundcheck any act against its crowd. No sign-up.",
};

export default function TryPage() {
  return (
    <>
      <section className="hero" aria-labelledby="h-try">
        <p className="eyebrow">Try it</p>
        <h1 id="h-try">Try a venue. No sign-up.</h1>
        <p>
          Each room below is a real venue. Its crowd is read from the public lineups of its past events and matched to Qloo, so the scores are
          provisional: nobody has scanned a QR code there. Check any act you like.
        </p>
      </section>

      <section aria-labelledby="h-venues">
        <h2 className="sr-only" id="h-venues">
          The demo venues
        </h2>
        <DemoVenues />
      </section>

      <FindVenue />

      <div className="two">
        <section className="card" aria-labelledby="h-how">
          <h2 className="card__title" id="h-how" style={{ marginBottom: "var(--s-3)" }}>
            How a demo venue is built
          </h2>
          <ul className="ticks">
            {[
              "Its past events and who played them come from MusicBrainz, which is public domain.",
              "Each act is looked up in Qloo by exact name. An act Qloo does not hold is left out, never guessed.",
              "Acts that share tastes are grouped into up to three scenes, and those scenes stand in for the crowd.",
              "A Soundcheck then asks Qloo how well an act fits each scene, and the score is computed in code.",
            ].map((t) => (
              <li key={t}>
                <Icon name="check" />
                {t}
              </li>
            ))}
          </ul>
        </section>
        <section className="card" aria-labelledby="h-lim">
          <h2 className="card__title" id="h-lim" style={{ marginBottom: "var(--s-3)" }}>
            What to keep in mind
          </h2>
          <ul className="ticks">
            {[
              "Lineups show who a room booked, not who came. A score from them is provisional and says so.",
              "Checking a new act calls Qloo, so each network can run a few every ten minutes and the whole site has a daily limit.",
              "Nothing you do here is tied to you: there is no account and no cookie. Your network address is used only, scrambled, to count how many checks one network runs.",
            ].map((t) => (
              <li key={t}>
                <Icon name="alert" />
                {t}
              </li>
            ))}
          </ul>
        </section>
      </div>
    </>
  );
}
