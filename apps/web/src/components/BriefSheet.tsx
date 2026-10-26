import { Label } from "@/components/Label";
import { longDate, type Brief } from "@/lib/brief";

const COLOURS = ["var(--t1)", "var(--t2)", "var(--t3)"];

/** The Booking Brief as a sheet of paper. Used by the owner's page and by the shared link, so they cannot differ. */
export function BriefSheet({ doc }: { doc: Brief }) {
  if (doc.status !== "ok" || !doc.basis) {
    return (
      <article className="paper" aria-label="Booking Brief" data-testid="brief" data-status="thin">
        <div>
          <p className="eyebrow">
            Booking Brief · {doc.venue.business} · {longDate(doc.date)}
          </p>
          <h1>{doc.title}</h1>
        </div>
        <hr />
        <section>
          <h2>Not enough data yet</h2>
          <p>{doc.reason}</p>
        </section>
      </article>
    );
  }
  return (
    <article className="paper" aria-label="Booking Brief" data-testid="brief" data-status="ok">
      <div>
        <p className="eyebrow">
          Booking Brief · {doc.venue.business} · {longDate(doc.date)}
        </p>
        <h1>{doc.title}</h1>
      </div>
      <hr />
      <section>
        <h2>Your crowd</h2>
        <div className="tribebar" role="img" aria-label={doc.groups.map((g) => `${g.label} ${g.share} percent`).join(", ")}>
          {doc.groups.map((g, i) => (
            <span key={g.label} style={{ ["--w" as string]: `${g.share}%`, ["--c" as string]: COLOURS[i % 3] }} />
          ))}
        </div>
        <table>
          <thead>
            <tr>
              <th>Group</th>
              <th className="num">{doc.basis.unit === "guests" ? "Guests" : "Acts"}</th>
              <th>When they come</th>
            </tr>
          </thead>
          <tbody>
            {doc.groups.map((g) => (
              <tr key={g.label}>
                <td>{g.label}</td>
                <td className="num">{doc.basis?.unit === "guests" ? `${g.size} of ${doc.basis.n}` : `${g.size} acts`}</td>
                <td>{g.when ?? (doc.basis?.unit === "guests" ? "Not enough scans yet to say" : "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="meta">
          <Label kind="measured" detail={`n = ${doc.basis.n}`} /> <Label kind="modelled" detail="groups" /> {doc.notes[0] ?? ""}
        </p>
      </section>
      <section>
        <h2>{doc.acts.length === 3 ? "Three acts to consider" : "Acts to consider"}</h2>
        <table className="brief-acts">
          <thead>
            <tr>
              <th>Act</th>
              <th className="num">Soundcheck</th>
              <th>Best for</th>
              <th>Watch out for</th>
            </tr>
          </thead>
          <tbody>
            {doc.acts.map((a) => (
              <tr key={a.name} data-testid="brief-act">
                <td>
                  <strong>{a.name}</strong>
                  {a.genres.length ? (
                    <>
                      <br />
                      <small>{a.genres.join(", ")}</small>
                    </>
                  ) : null}
                  <br />
                  <small>Fit by group: {a.groups.map((g) => `${g.label} ${g.fit}`).join(" · ")}</small>
                </td>
                <td className="num" data-label="Soundcheck">
                  {a.score}
                  <br />
                  <small>
                    range {a.band[0]} to {a.band[1]}
                  </small>
                </td>
                <td data-label="Best for">{a.best_for}</td>
                <td data-label="Watch out for">{a.watch ?? "Nothing stands out."}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <div className="grid2">
        <section>
          <h2>This month’s Wildcard</h2>
          {doc.wildcard ? (
            <>
              <p>
                <strong>{doc.wildcard.name}</strong>
                {doc.wildcard.genres.length ? ` (${doc.wildcard.genres.join(", ")})` : ""}
              </p>
              <p>
                Soundcheck {doc.wildcard.score}, range {doc.wildcard.band[0]} to {doc.wildcard.band[1]}. A small act that ranks well for your two biggest
                groups. <Label kind="modelled" />
              </p>
            </>
          ) : (
            <p>No small act ranked well for both of your biggest groups this time.</p>
          )}
        </section>
        <section>
          <h2>Best nights</h2>
          <p>{doc.nights ? doc.nights.text : "No night stands out for these acts."}</p>
          <p>
            <Label kind="modelled" />
          </p>
        </section>
      </div>
      <hr />
      <footer>
        <p>
          <strong>How this was computed.</strong> {doc.how}
        </p>
        {doc.notes.slice(1).map((n) => (
          <p key={n}>{n}</p>
        ))}
        <p>Taste data from Qloo. This brief holds item names, genre labels and our own scores only, and groups under 10 people are never shown.</p>
      </footer>
    </article>
  );
}
