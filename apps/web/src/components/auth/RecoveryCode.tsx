"use client";

import { useState } from "react";
import { Icon } from "@/components/Icon";
import { recoveryFile } from "@/lib/account";

/**
 * The recovery code, shown once. There is no emailed reset, so this code is the only way back in after a forgotten password: the
 * person has to say they have kept it before they can go on.
 */
export function RecoveryCode({ code, email, heading, onDone, doneLabel = "Continue", level = "h1" }: { code: string; email: string; heading: string; onDone: () => void; doneLabel?: string; level?: "h1" | "h3" }) {
  const Heading = level;
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState<"yes" | "no" | null>(null);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied("yes");
    } catch {
      setCopied("no");
    }
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([recoveryFile(email, code)], { type: "text/plain" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "nigiwai-recovery-code.txt";
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="stack" data-testid="recovery">
      <div>
        <Heading className={level === "h1" ? "display" : "tm-sub"}>{heading}</Heading>
        <p className="muted" style={{ marginTop: "var(--s-2)" }}>
          Nigiwai does not email password resets. If you forget your password, this code is the only way back in, and it is shown only now. Keep it
          somewhere private: a password manager, or a printed copy.
        </p>
      </div>
      <p className="rc-code" data-testid="recovery-code">
        {code}
      </p>
      <div className="row row--wrap">
        <button className="btn" type="button" data-testid="recovery-copy" onClick={() => void copy()}>
          <Icon name="copy" />
          Copy
        </button>
        <button className="btn" type="button" data-testid="recovery-download" onClick={download}>
          <Icon name="download" />
          Save as a file
        </button>
      </div>
      <p className="meta" role="status">
        {copied === "yes" ? "Copied." : copied === "no" ? "Your browser would not copy it. Select the code and copy it by hand." : " "}
      </p>
      <label className="check">
        <input type="checkbox" data-testid="recovery-saved" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
        <span>I have saved this code somewhere I can find it.</span>
      </label>
      <button className="btn btn--primary btn--lg" type="button" data-testid="recovery-continue" disabled={!saved} onClick={onDone}>
        {doneLabel}
      </button>
    </div>
  );
}
