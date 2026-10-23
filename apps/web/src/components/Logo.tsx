import Link from "next/link";

/** The Direction A mark with the wordmark. */
export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link className="logo" href={href} aria-label="Nigiwai home">
      <span className="logo__mark" aria-hidden="true">
        <svg className="m-a" viewBox="0 0 40 40">
          <use href="#logo-a" />
        </svg>
      </span>
      <span className="logo__word">Nigiwai</span>
    </Link>
  );
}
