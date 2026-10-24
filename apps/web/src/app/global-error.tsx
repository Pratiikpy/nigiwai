"use client";

/** The last resort: the page frame itself failed, so no stylesheet or component can be relied on. */
export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, fontFamily: "system-ui, sans-serif", background: "#f3eada", color: "#1b2030" }}>
        <main style={{ maxWidth: "32rem", margin: "0 auto", padding: "4rem 1rem" }}>
          <h1 style={{ fontSize: "2rem", lineHeight: 1.1 }}>Something went wrong.</h1>
          <p style={{ lineHeight: 1.5 }}>It is on our side, not yours. Try again, and if it keeps happening, come back a little later.</p>
          <button type="button" onClick={() => reset()} style={{ font: "inherit", fontWeight: 700, padding: "0.75rem 1.25rem", border: "2px solid #1b2030", borderRadius: "0.75rem", background: "#fff", cursor: "pointer" }}>
            Try again
          </button>
        </main>
      </body>
    </html>
  );
}
