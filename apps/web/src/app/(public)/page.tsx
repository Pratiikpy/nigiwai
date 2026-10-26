import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { DemoVenues } from "@/components/DemoVenues";
import { Icon } from "@/components/Icon";

export const metadata: Metadata = {
  title: { absolute: "Nigiwai: soundcheck any act on your crowd before you book it" },
  description:
    "See who your room really draws, how well an act fits each group, and what the numbers rest on. Try three real venues with no sign-up.",
};

export default function Home() {
  return (
    <>
      <section className="hero hero--split" aria-labelledby="h-hero">
        <div className="hero__copy">
          <p className="eyebrow">For rooms that book music</p>
          <h1 id="h-hero">Soundcheck any act on your crowd before you book it.</h1>
          <p>
            See who your room really draws, how well an act fits each group, and what the numbers rest on. Every score shows its working and the
            Qloo calls behind it.
          </p>
          <div className="row row--wrap">
            <Link className="btn btn--primary btn--lg" href="/try">
              <Icon name="bolt" />
              Try a venue
            </Link>
            <Link className="btn btn--lg" href="/evidence">
              <Icon name="list" />
              Read the evidence
            </Link>
            <a className="btn btn--lg" href="https://youtu.be/3dFhP7JRtY0" target="_blank" rel="noopener noreferrer">
              <Icon name="screen" />
              Watch the 2-minute film
            </a>
          </div>
        </div>
        <figure className="hero__figure">
          <Image
            src="/img/sample-soundcheck.png"
            alt="A Soundcheck: an act scored 94 out of 100 for a crowd, with its range, how each of the crowd's three groups ranks it, why it fits, what to watch out for and the nights it suits"
            width={606}
            height={768}
            unoptimized
            priority
          />
          <figcaption className="meta">A Soundcheck on a made-up room and an invented act, so no Qloo data is shown here. Open a real room below.</figcaption>
        </figure>
      </section>

      <section aria-labelledby="h-v">
        <h2 className="card__title" id="h-v" style={{ marginBottom: "var(--s-3)" }}>
          Try a venue. No sign-up.
        </h2>
        <DemoVenues />
      </section>

      <section className="facts" aria-label="Why you can trust it">
        <div className="fact">
          <Icon name="check" />
          <h3>Real items only</h3>
          <p>Every act and place shown comes from a Qloo result or from public lineups. A check in code rejects anything that does not.</p>
        </div>
        <div className="fact">
          <Icon name="compare" />
          <h3>The comparison is on screen</h3>
          <p>
            Beside each check, the same question goes to an AI alone, with ties shown as ties. If no AI can answer, the panel says so instead of
            guessing.
          </p>
        </div>
        <div className="fact">
          <Icon name="shield" />
          <h3>Private by design</h3>
          <p>
            The guest survey takes no names, emails or device IDs, and groups under 10 people are never shown. <Link href="/privacy">Read the privacy page</Link>.
          </p>
        </div>
      </section>

      <section className="card" aria-labelledby="h-own">
        <h2 className="card__title" id="h-own" style={{ marginBottom: "var(--s-3)" }}>
          Run it on your own room
        </h2>
        <p style={{ marginBottom: "var(--s-4)" }}>
          Create an account, print a QR code for the bar, and your guests’ favourites become a map of your crowd and a Soundcheck for every act you
          are thinking of booking. You can start from your venue’s public lineups the same afternoon.
        </p>
        <div className="row row--wrap">
          <Link className="btn btn--primary" href="/signup">
            Create an account
          </Link>
          <Link className="btn" href="/login">
            Owner sign in
          </Link>
        </div>
      </section>
    </>
  );
}
