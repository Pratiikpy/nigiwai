import { Icon } from "./Icon";

export type LabelKind = "measured" | "observed" | "modelled";

const TEXT: Record<LabelKind, string> = { measured: "Measured", observed: "Observed", modelled: "Modelled" };
const MEANING: Record<LabelKind, string> = {
  measured: "Counted from your guests' own scans.",
  observed: "Looked up in Qloo's data.",
  modelled: "Our inference from the two above: a hypothesis to check, not a fact.",
};

/** The three honesty labels. Colour is never the only signal: each has its own shape and its word. */
export function Label({ kind, detail }: { kind: LabelKind; detail?: string }) {
  return (
    <span className="lbl" data-kind={kind} title={MEANING[kind]}>
      <svg className="ic" aria-hidden="true" focusable="false">
        <use href={`#lbl-${kind}`} />
      </svg>
      <span className="lbl__t">{TEXT[kind]}</span>
      {detail ? <span className="lbl__x">{detail}</span> : null}
    </span>
  );
}

export { Icon };
