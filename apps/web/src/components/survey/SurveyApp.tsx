"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { Sheet } from "@/components/Sheet";
import {
  ApiError,
  api,
  type PickerItem,
  type PickerResult,
  type PickerType,
  type PublicSurvey,
  type ResponseResult,
  type SelectResult,
} from "@/lib/api";
import {
  AGE_BANDS,
  BUDGETS,
  CATEGORIES,
  ageLabel,
  clearDraft,
  countLine,
  districtProblem,
  loadDraft,
  metaLine,
  parseConsent,
  pickProgress,
  saveDraft,
} from "@/lib/survey";
import { ShareSheet, TasteCard } from "./TasteCard";
import { Tile } from "./Tile";

type Load =
  | { s: "loading" }
  | { s: "closed" }
  | { s: "error"; message: string }
  | { s: "ready"; survey: PublicSurvey };

type Screen = "consent" | "pick" | "about" | "done";
type View =
  | { s: "idle" }
  | { s: "loading"; q: string; slow: boolean }
  | { s: "results"; q: string; items: PickerItem[]; note: string | null }
  | { s: "empty"; q: string; note: string | null }
  | { s: "error"; q: string; message: string };

const DEBOUNCE_MS = 300;
const SLOW_MS = 2200;

function message(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429) return "That's a lot in a short time. Wait a moment, then try again.";
    return error.detail;
  }
  return "Something went wrong. Please try again.";
}

/** Fetches the survey for a QR token. The nonce it returns identifies this one sitting. */
export function SurveyApp({ token }: { token: string }) {
  const [load, setLoad] = useState<Load>({ s: "loading" });

  const fetchSurvey = useCallback(async (): Promise<PublicSurvey> => {
    return api<PublicSurvey>(`/public/survey/${encodeURIComponent(token)}`);
  }, [token]);

  useEffect(() => {
    let live = true;
    fetchSurvey()
      .then((survey) => live && setLoad({ s: "ready", survey }))
      .catch((error: unknown) => {
        if (!live) return;
        if (error instanceof ApiError && error.status === 404) setLoad({ s: "closed" });
        else setLoad({ s: "error", message: message(error) });
      });
    return () => {
      live = false;
    };
  }, [fetchSurvey]);

  if (load.s === "ready") return <Flow token={token} first={load.survey} refresh={fetchSurvey} onClosed={() => setLoad({ s: "closed" })} />;

  return (
    <div className="survey-stage">
      <div className="phone">
        <main className="s-main" id="main" tabIndex={-1}>
          {load.s === "loading" ? (
            <div className="res-status" role="status" style={{ marginTop: "var(--s-8)" }}>
              <span className="spin" aria-hidden="true" />
              Opening the survey…
            </div>
          ) : load.s === "closed" ? (
            <section className="closed" aria-labelledby="closed-h">
              <h1 className="display" id="closed-h">
                This survey isn&rsquo;t open right now.
              </h1>
              <p className="muted">
                The poster may have been replaced, or the venue has paused the survey. Ask the venue for the current
                code.
              </p>
            </section>
          ) : (
            <section className="closed" aria-labelledby="err-h">
              <h1 className="display" id="err-h">
                We couldn&rsquo;t open the survey.
              </h1>
              <p className="muted">{load.message}</p>
              <button className="btn btn--primary" type="button" onClick={() => location.reload()}>
                <Icon name="refresh" />
                Try again
              </button>
            </section>
          )}
        </main>
      </div>
    </div>
  );
}

function Flow({
  token,
  first,
  refresh,
  onClosed,
}: {
  token: string;
  first: PublicSurvey;
  refresh: () => Promise<PublicSurvey>;
  onClosed: () => void;
}) {
  const survey = first;
  const q = survey.questions;
  const nonce = useRef(first.nonce);
  const [screen, setScreen] = useState<Screen>("consent");
  // Flow only mounts in the browser, after the survey has loaded, so the saved draft can seed the state directly.
  const [saved] = useState(() => loadDraft(token));
  const [picks, setPicks] = useState<PickerItem[]>(() => saved?.picks.slice(0, first.questions.max_picks) ?? []);
  const [age, setAge] = useState<string | null>(saved?.age ?? null);
  const [district, setDistrict] = useState(saved?.district ?? "");
  const [budget, setBudget] = useState<number | null>(saved?.budget ?? null);
  const [popId, setPopId] = useState<string | null>(null);
  const [liveMsg, setLiveMsg] = useState("");
  const [sheet, setSheet] = useState<"notice" | "remove" | "share" | null>(null);
  const [honeypot, setHoneypot] = useState("");
  const [result, setResult] = useState<ResponseResult | null>(null);
  const mainRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (screen === "done") return;
    saveDraft(token, { picks, age, district, budget });
  }, [token, screen, picks, age, district, budget]);

  const announce = useCallback((text: string) => {
    setLiveMsg("");
    setTimeout(() => setLiveMsg(text), 30);
  }, []);

  /** POST to a public endpoint. A 403 means the page's nonce expired: fetch a fresh one and retry once. */
  const call = useCallback(
    async <T,>(path: string, build: (nonce: string) => Record<string, unknown>, signal?: AbortSignal): Promise<T> => {
      const send = (n: string) => api<T>(path, { method: "POST", body: build(n), signal });
      try {
        return await send(nonce.current);
      } catch (error) {
        if (error instanceof ApiError && error.status === 403) {
          try {
            const fresh = await refresh();
            nonce.current = fresh.nonce;
          } catch (again) {
            if (again instanceof ApiError && again.status === 404) onClosed();
            throw again;
          }
          return send(nonce.current);
        }
        if (error instanceof ApiError && error.status === 404) onClosed();
        throw error;
      }
    },
    [refresh, onClosed],
  );

  // ---- screens ---------------------------------------------------------------------------------------------------
  const go = (next: Screen) => {
    setScreen(next);
    requestAnimationFrame(() => {
      mainRef.current?.scrollTo({ top: 0 });
      mainRef.current?.focus({ preventScroll: true });
    });
  };

  const progress = pickProgress(picks.length, q.min_picks, q.max_picks);
  const districtError = districtProblem(district);
  const step = screen === "pick" ? 1 : screen === "about" ? 2 : screen === "done" ? 3 : 0;
  const stepText =
    step === 1
      ? "Step 1 of 3 · Your picks"
      : step === 2
        ? "Step 2 of 3 · Review and send"
        : "Step 3 of 3 · Your card";

  const removePick = (id: string) => {
    setPicks((p) => p.filter((x) => x.entity_id !== id));
    announce("Removed.");
  };

  return (
    <div className="survey-stage">
      <div className="phone">
        <header className="s-head" inert={sheet !== null}>
          <div className="venue">
            <span className="venue__mark" aria-hidden="true">
              {Array.from(survey.business_name)[0]?.toUpperCase() ?? "N"}
            </span>
            <span className="venue__txt">
              <strong>{survey.business_name}</strong>
              <span className="meta">You scanned: {survey.qr_label}</span>
            </span>
          </div>
          <button
            className="privacy"
            type="button"
            onClick={() => setSheet("notice")}
            aria-label="Anonymous. Read how your picks are used"
          >
            <Icon name="lock" size="sm" />
            <span>Anonymous</span>
          </button>
        </header>

        {step > 0 ? (
          <div className="progress" data-step={step} inert={sheet !== null} role="region" aria-label="Progress">
            <p className="progress__t">{stepText}</p>
            <div className="progress__bar" aria-hidden="true">
              <i />
              <i />
              <i />
            </div>
          </div>
        ) : null}

        <main className="s-main" id="main" tabIndex={-1} ref={mainRef} inert={sheet !== null}>
          {screen === "consent" ? (
            <ConsentScreen survey={survey} onNotice={() => setSheet("notice")} onRemove={() => setSheet("remove")} />
          ) : null}
          {screen === "pick" ? (
            <PickScreen
              survey={survey}
              picks={picks}
              popId={popId}
              call={call}
              token={token}
              announce={announce}
              onAdd={(item) => {
                setPicks((p) => [...p, item]);
                setPopId(item.entity_id);
                announce(`${item.name} added. ${picks.length + 1} of ${q.max_picks}.`);
              }}
              onRemove={removePick}
            />
          ) : null}
          {screen === "about" ? (
            <AboutScreen
              survey={survey}
              picks={picks}
              age={age}
              setAge={setAge}
              district={district}
              setDistrict={setDistrict}
              districtError={districtError}
              budget={budget}
              setBudget={setBudget}
              honeypot={honeypot}
              setHoneypot={setHoneypot}
            />
          ) : null}
          {screen === "done" && result ? (
            <TasteCard
              receipt={result.receipt}
              reward={result.reward}
              businessName={survey.business_name}
              onRemove={() => setSheet("remove")}
              onShare={() => setSheet("share")}
            />
          ) : null}
        </main>

        {screen !== "done" ? (
          <Footer
            screen={screen}
            survey={survey}
            picks={picks}
            canContinue={progress.canContinue}
            progressText={progress.text}
            districtBlocked={districtError !== null}
            inert={sheet !== null}
            onBack={() => go(screen === "about" ? "pick" : "consent")}
            onNext={() => go(screen === "consent" ? "pick" : "about")}
            call={call}
            token={token}
            age={age}
            district={district}
            budget={budget}
            honeypot={honeypot}
            onSent={(sent) => {
              clearDraft(token);
              setResult(sent);
              go("done");
            }}
          />
        ) : null}

        <Sheet
          open={sheet === "notice"}
          onClose={() => setSheet(null)}
          title="How your picks are used"
          subtitle={`Notice ${survey.consent_text_version}`}
        >
          <div className="notice">
            {parseConsent(survey.consent_body).map((paragraph, i) => (
              <p key={i} style={{ marginBottom: "var(--s-3)" }}>
                {paragraph.map((segment, j) =>
                  segment.strong ? <strong key={j} style={{ color: "var(--ink)" }}>{segment.text}</strong> : segment.text,
                )}
              </p>
            ))}
          </div>
        </Sheet>

        {result ? (
          <ShareSheet open={sheet === "share"} onClose={() => setSheet(null)} receipt={result.receipt} />
        ) : null}

        <RemoveSheet
          open={sheet === "remove"}
          initialCode={screen === "done" ? (result?.receipt ?? "") : ""}
          onClose={() => setSheet(null)}
        />

        <div className="sr-live" role="status" aria-live="polite">
          {liveMsg}
        </div>
      </div>
    </div>
  );
}

// ---- consent ----------------------------------------------------------------------------------------------------
function ConsentScreen({
  survey,
  onNotice,
  onRemove,
}: {
  survey: PublicSurvey;
  onNotice: () => void;
  onRemove: () => void;
}) {
  const q = survey.questions;
  return (
    <section className="screen" aria-labelledby="h-consent">
      <div className="hero">
        <div className="deco" aria-hidden="true">
          <span className="da" />
        </div>
        <p className="eyebrow">{survey.business_name}</p>
        <h1 className="display hero__h" id="h-consent">
          Tell us what <em>you love.</em>
        </h1>
        <p className="hero__lead">
          Pick {q.min_picks === q.max_picks ? q.max_picks : `${q.min_picks} to ${q.max_picks}`} favourites: music,
          shows, films, books and more. You get a Taste Card back, and {survey.business_name} learns what its guests love.
        </p>
      </div>

      {survey.reward ? (
        <div className="gift">
          <Icon name="gift" />
          <p>
            <strong>A thank-you at the end:</strong> {survey.reward.title}.
          </p>
        </div>
      ) : null}

      <section className="card privacy-card" aria-labelledby="h-priv">
        <h2 className="card__title" id="h-priv">
          Your picks, not you
        </h2>
        <div className="priv-grid">
          <div>
            <h3 className="eyebrow">We keep</h3>
            <ul className="ticks">
              <li>
                <Icon name="check" />
                The things you pick
              </li>
              <li>
                <Icon name="check" />
                The day and hour you answer, and which poster
              </li>
              <li>
                <Icon name="check" />
                Age range, area, budget: only if you add them
              </li>
            </ul>
          </div>
          <div>
            <h3 className="eyebrow">We never ask for</h3>
            <ul className="ticks ticks--no">
              <li>
                <Icon name="nouser" />
                Your name or email
              </li>
              <li>
                <Icon name="nouser" />
                Phone number or device ID
              </li>
              <li>
                <Icon name="nouser" />
                Your location
              </li>
            </ul>
          </div>
        </div>
        <p className="meta priv-foot">
          Nothing is saved until you press Send. Qloo, the taste service we use, may keep and reuse what you search for
          and choose, never linked to you. This survey is for people 18 and over.{" "}
          <button type="button" className="linklike" onClick={onNotice}>
            Read the full notice
          </button>
        </p>
      </section>

      <p className="meta" style={{ marginTop: "var(--s-4)" }}>
        Already answered?{" "}
        <button type="button" className="linklike" onClick={onRemove}>
          Remove my answers
        </button>
      </p>
    </section>
  );
}

// ---- picker -----------------------------------------------------------------------------------------------------
type Call = <T>(path: string, build: (nonce: string) => Record<string, unknown>, signal?: AbortSignal) => Promise<T>;

function PickScreen({
  survey,
  picks,
  popId,
  call,
  token,
  announce,
  onAdd,
  onRemove,
}: {
  survey: PublicSurvey;
  picks: PickerItem[];
  popId: string | null;
  call: Call;
  token: string;
  announce: (text: string) => void;
  onAdd: (item: PickerItem) => void;
  onRemove: (id: string) => void;
}) {
  const q = survey.questions;
  const [category, setCategory] = useState<"all" | PickerType>("all");
  const [query, setQuery] = useState("");
  const [view, setView] = useState<View>({ s: "idle" });
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: "warn" | "error"; text: string } | null>(null);
  const seq = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const minChars = survey.picker_min_chars;
  const full = picks.length >= q.max_picks;

  const run = useCallback(
    async (text: string, cat: "all" | PickerType) => {
      const my = ++seq.current;
      controller.current?.abort();
      const ctl = new AbortController();
      controller.current = ctl;
      setView({ s: "loading", q: text, slow: false });
      const slow = setTimeout(() => {
        if (my === seq.current) setView((v) => (v.s === "loading" ? { ...v, slow: true } : v));
      }, SLOW_MS);
      try {
        const result = await call<PickerResult>(
          "/public/picker",
          (nonce) => ({ token, nonce, q: text, ...(cat === "all" ? {} : { type: cat }) }),
          ctl.signal,
        );
        if (my !== seq.current) return;
        if (result.items.length) {
          setView({ s: "results", q: text, items: result.items, note: result.message });
          announce(`${result.items.length} ${result.items.length === 1 ? "match" : "matches"}`);
        } else {
          setView({ s: "empty", q: text, note: result.message });
          announce("No matches");
        }
      } catch (error) {
        if (my !== seq.current || (error instanceof DOMException && error.name === "AbortError")) return;
        setView({ s: "error", q: text, message: message(error) });
        announce("The search failed.");
      } finally {
        clearTimeout(slow);
      }
    },
    [call, token, announce],
  );

  const tooShort = Array.from(query.trim()).length < minChars;
  const shown: View = tooShort ? { s: "idle" } : view;

  useEffect(() => {
    const text = query.trim();
    if (tooShort) {
      // Nothing to search for: drop any search still in flight so a late answer cannot appear.
      seq.current++;
      controller.current?.abort();
      return;
    }
    const timer = setTimeout(() => void run(text, category), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query, category, tooShort, run]);

  useEffect(() => () => controller.current?.abort(), []);

  const add = async (item: PickerItem) => {
    if (pendingId || full || picks.some((p) => p.entity_id === item.entity_id)) return;
    setPendingId(item.entity_id);
    setNotice(null);
    try {
      const result = await call<SelectResult>("/public/select", (nonce) => ({
        token,
        nonce,
        entity_id: item.entity_id,
      }));
      if (result.eligible === false) {
        setNotice({ tone: "warn", text: result.message ?? "We can't use that one. Please choose another favourite." });
        return;
      }
      onAdd(item);
    } catch (error) {
      setNotice({ tone: "error", text: message(error) });
    } finally {
      setPendingId(null);
    }
  };

  const isPicked = (id: string) => picks.some((p) => p.entity_id === id);
  const slots = Array.from({ length: q.max_picks }, (_, i) => picks[i]);

  return (
    <section className="screen" aria-labelledby="h-pick">
      <div className="stack">
        <div>
          <h1 className="display pick__h" id="h-pick">
            What do you love?
          </h1>
          <p className="muted">
            Pick {q.min_picks === q.max_picks ? q.max_picks : `${q.min_picks} to ${q.max_picks}`}. Start typing, then
            choose from the list.
          </p>
        </div>

        <div>
          <ol
            className="slots"
            aria-label="Your picks"
            style={{ gridTemplateColumns: `repeat(${Math.min(q.max_picks, 5)}, 1fr)` }}
          >
            {slots.map((pick, i) => (
              <li key={pick?.entity_id ?? `empty-${i}`}>
                {pick ? (
                  <button
                    className={`slot is-filled${popId === pick.entity_id ? " is-pop" : ""}`}
                    type="button"
                    onClick={() => onRemove(pick.entity_id)}
                    aria-label={`Remove ${pick.name}`}
                  >
                    <Tile name={pick.name} type={pick.type} />
                    <span className="slot__x" aria-hidden="true">
                      <Icon name="x" />
                    </span>
                  </button>
                ) : (
                  <span className="slot" aria-label={`Empty slot ${i + 1}`}>
                    {i + 1}
                  </span>
                )}
              </li>
            ))}
          </ol>
          <p className={`count${picks.length >= q.max_picks ? " is-full" : ""}`} aria-live="polite">
            {picks.length >= q.max_picks ? <Icon name="check" size="sm" /> : null}
            {countLine(picks.length, q.max_picks)}
          </p>
        </div>

        {q.picker_types.length > 1 ? (
          <div className="chips cats" role="group" aria-label="Search in">
            <button
              className="chipbtn"
              type="button"
              data-cat="all"
              aria-pressed={category === "all"}
              onClick={() => setCategory("all")}
            >
              All
            </button>
            {q.picker_types.map((t) => (
              <button
                key={t}
                className="chipbtn"
                type="button"
                aria-pressed={category === t}
                onClick={() => setCategory(t)}
              >
                <Icon name={CATEGORIES[t].icon} />
                {CATEGORIES[t].label}
              </button>
            ))}
          </div>
        ) : null}

        <div className="field">
          <label htmlFor="q">Search</label>
          <div className="search">
            <Icon name="search" />
            <input
              className="input"
              id="q"
              type="search"
              inputMode="search"
              enterKeyHint="search"
              autoComplete="off"
              autoCapitalize="off"
              spellCheck={false}
              maxLength={80}
              placeholder="Band, show, film, book or brand"
              aria-controls="results"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            {query ? (
              <button className="iconbtn search__clear" type="button" aria-label="Clear search" onClick={() => setQuery("")}>
                <Icon name="x" />
              </button>
            ) : null}
          </div>
        </div>

        {notice ? (
          <div className="banner" data-tone={notice.tone === "warn" ? "warn" : "error"} role="alert">
            <Icon name="alert" />
            <div className="banner__body">{notice.text}</div>
          </div>
        ) : null}

        <div id="results" className="results" aria-busy={shown.s === "loading"}>
          {shown.s === "idle" ? (
            <p className="res-hint">Type {minChars} or more letters. Search for a band, a show, a film, a book or a brand.</p>
          ) : null}

          {shown.s === "loading" ? (
            <>
              <div className="res-status" role="status">
                <span className="spin" aria-hidden="true" />
                {shown.slow ? "Still looking. This one is taking longer than usual." : <>Looking for “{shown.q}”…</>}
              </div>
              <div className="card res-card" aria-hidden="true">
                {[0, 1, 2].map((i) => (
                  <div className="skelrow" key={i}>
                    <span className="skel skel--tile" />
                    <div>
                      <span className="skel skel--line-l" />
                      <span className="skel skel--line-m" />
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : null}

          {shown.s === "results" ? (
            <>
              {full ? (
                <div className="banner" data-tone="ok">
                  <Icon name="check" />
                  <div className="banner__body">You have {q.max_picks}. Tap a pick above to remove it and swap.</div>
                </div>
              ) : null}
              <div className="res-status">
                {shown.items.length} {shown.items.length === 1 ? "match" : "matches"} for “{shown.q}”
              </div>
              <ul className="card res-card" role="list">
                {shown.items.map((item) => {
                  const picked = isPicked(item.entity_id);
                  const pending = pendingId === item.entity_id;
                  return (
                    <li className="result" key={item.entity_id}>
                      <Tile name={item.name} type={item.type} />
                      <div className="result__t">
                        <strong>{item.name}</strong>
                        <span className="meta">{metaLine(item)}</span>
                        {item.description ? <span className="result__d">{item.description}</span> : null}
                      </div>
                      <button
                        className="btn btn--sm"
                        type="button"
                        onClick={() => (picked ? onRemove(item.entity_id) : void add(item))}
                        aria-pressed={picked}
                        disabled={(full && !picked) || (pendingId !== null && !pending)}
                        aria-label={`${picked ? "Remove" : "Add"} ${item.name}`}
                      >
                        {pending ? (
                          <>
                            <span className="spin pending-spin" aria-hidden="true" />
                            Checking
                          </>
                        ) : picked ? (
                          <>
                            <Icon name="check" size="sm" />
                            Added
                          </>
                        ) : (
                          <>
                            <Icon name="plus" size="sm" />
                            Add
                          </>
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
              {shown.note ? <p className="res-note">{shown.note}</p> : null}
            </>
          ) : null}

          {shown.s === "empty" ? (
            <div className="card card--flat res-empty">
              <div className="empty empty--inline">
                <div className="empty__art">
                  <svg viewBox="0 0 112 88" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <circle cx="46" cy="38" r="22" />
                    <path d="M62 54l22 20" />
                    <path d="M36 38h20" strokeDasharray="1 7" />
                    <circle cx="92" cy="22" r="5" fill="var(--highlight)" stroke="none" />
                    <circle cx="20" cy="70" r="4" fill="var(--brand)" stroke="none" />
                  </svg>
                </div>
                <h2>Nothing called “{shown.q}” yet.</h2>
                <p>Check the spelling, or try just the name of the band or title. You can also look in another category.</p>
                {shown.note ? <p className="res-note">{shown.note}</p> : null}
                <button className="btn btn--sm" type="button" onClick={() => setQuery("")}>
                  Clear search
                </button>
              </div>
            </div>
          ) : null}

          {shown.s === "error" ? (
            <div className="card card--flat res-empty">
              <div className="empty empty--inline">
                <h2>We couldn&rsquo;t reach the search.</h2>
                <p>{shown.message} Your picks are safe on this phone.</p>
                <button className="btn btn--primary" type="button" onClick={() => void run(shown.q, category)}>
                  <Icon name="refresh" />
                  Try again
                </button>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

// ---- about / review ---------------------------------------------------------------------------------------------
function AboutScreen({
  survey,
  picks,
  age,
  setAge,
  district,
  setDistrict,
  districtError,
  budget,
  setBudget,
  honeypot,
  setHoneypot,
}: {
  survey: PublicSurvey;
  picks: PickerItem[];
  age: string | null;
  setAge: (v: string | null) => void;
  district: string;
  setDistrict: (v: string) => void;
  districtError: string | null;
  budget: number | null;
  setBudget: (v: number | null) => void;
  honeypot: string;
  setHoneypot: (v: string) => void;
}) {
  const q = survey.questions;
  const optional: string[] = [];
  if (q.ask_age_band && age) optional.push(`age range ${ageLabel(age)}`);
  if (q.ask_district && district.trim() && !districtError) optional.push(`area ${district.trim()}`);
  if (q.ask_budget && budget) optional.push(`spend ${"$".repeat(budget)}`);
  const anyAsked = q.ask_age_band || q.ask_district || q.ask_budget;

  return (
    <section className="screen" aria-labelledby="h-about">
      <div className="stack stack--lg">
        <div>
          <h1 className="display pick__h" id="h-about">
            {anyAsked ? "A little about you" : "Ready to send?"}
          </h1>
          <p className="muted">{anyAsked ? "All optional. Skip any of it, or all of it." : "Check what you are sending."}</p>
        </div>

        {q.ask_age_band ? (
          <fieldset className="qset">
            <legend>Age range</legend>
            <div className="chips" role="group" aria-label="Age range">
              {AGE_BANDS.map((band) => (
                <button
                  key={band}
                  className="chipbtn"
                  type="button"
                  aria-pressed={age === band}
                  onClick={() => setAge(age === band ? null : band)}
                >
                  {ageLabel(band)}
                </button>
              ))}
            </div>
            <p className="field__hint">Tap again to clear.</p>
          </fieldset>
        ) : null}

        {q.ask_district && q.districts?.length ? (
          <fieldset className="qset" data-testid="district-choices">
            <legend>Where do you usually spend your day?</legend>
            <div className="chips">
              {q.districts.map((name) => (
                <button
                  key={name}
                  type="button"
                  className="chipbtn"
                  aria-pressed={district === name}
                  onClick={() => setDistrict(district === name ? "" : name)}
                >
                  {name}
                </button>
              ))}
            </div>
            <p className="field__hint">Tap again to clear.</p>
          </fieldset>
        ) : q.ask_district ? (
          <div className="field">
            <label htmlFor="district">Where do you usually spend your day?</label>
            <input
              className="input"
              id="district"
              type="text"
              autoComplete="off"
              maxLength={60}
              placeholder="A district or neighbourhood"
              value={district}
              onChange={(e) => setDistrict(e.target.value)}
              aria-invalid={districtError !== null}
              aria-describedby="district-hint"
            />
            {districtError ? (
              <p className="field__err" id="district-hint" role="alert">
                <Icon name="alert" size="sm" />
                {districtError}
              </p>
            ) : (
              <p className="field__hint" id="district-hint">
                A district, never an address.
              </p>
            )}
          </div>
        ) : null}

        {q.ask_budget ? (
          <fieldset className="qset">
            <legend>Usual spend when you go out</legend>
            <div className="chips" role="group" aria-label="Usual spend">
              {BUDGETS.map((b) => (
                <button
                  key={b.value}
                  className="chipbtn"
                  type="button"
                  aria-pressed={budget === b.value}
                  onClick={() => setBudget(budget === b.value ? null : b.value)}
                >
                  {b.label}
                </button>
              ))}
            </div>
          </fieldset>
        ) : null}

        <p className="note">
          <Icon name="shield" />
          <span>{survey.business_name} only ever sees group totals, and only for groups of 10 or more people.</span>
        </p>

        <section className="card card--flat sendlist" aria-labelledby="h-send">
          <h2 className="card__title" id="h-send">
            What you&rsquo;ll send
          </h2>
          <ul className="sendlist__items">
            <li>
              <Icon name="check" />
              <span>
                <strong>
                  {picks.length} {picks.length === 1 ? "pick" : "picks"}:
                </strong>{" "}
                {picks.map((p) => p.name).join(", ")}
              </span>
            </li>
            <li>
              <Icon name="check" />
              <span>
                <strong>Poster and time:</strong> {survey.qr_label}, and the day and hour, added automatically
              </span>
            </li>
            {anyAsked ? (
              <li>
                <Icon name={optional.length ? "check" : "minus"} />
                <span>
                  <strong>Optional:</strong> {optional.length ? optional.join(", ") : "nothing added"}
                </span>
              </li>
            ) : null}
          </ul>
          <p className="meta sendlist__no">
            <Icon name="nouser" size="sm" />
            Not sent: name, email, device ID, location.
          </p>
        </section>

        {/* A field a person never sees. A script that fills in every field gives itself away. */}
        <div className="hp" aria-hidden="true">
          <label htmlFor="website">Website</label>
          <input
            id="website"
            name="website"
            type="text"
            tabIndex={-1}
            autoComplete="off"
            value={honeypot}
            onChange={(e) => setHoneypot(e.target.value)}
          />
        </div>
      </div>
    </section>
  );
}

// ---- footer -----------------------------------------------------------------------------------------------------
function Footer({
  screen,
  survey,
  picks,
  canContinue,
  progressText,
  districtBlocked,
  inert,
  onBack,
  onNext,
  call,
  token,
  age,
  district,
  budget,
  honeypot,
  onSent,
}: {
  screen: Screen;
  survey: PublicSurvey;
  picks: PickerItem[];
  canContinue: boolean;
  progressText: string;
  districtBlocked: boolean;
  inert: boolean;
  onBack: () => void;
  onNext: () => void;
  call: Call;
  token: string;
  age: string | null;
  district: string;
  budget: number | null;
  honeypot: string;
  onSent: (result: ResponseResult) => void;
}) {
  const q = survey.questions;
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    if (sending) return;
    setSending(true);
    setError(null);
    try {
      const result = await call<ResponseResult>("/public/response", (nonce) => ({
        token,
        nonce,
        picks: picks.map((p) => p.entity_id),
        age_band: q.ask_age_band ? age : null,
        district: q.ask_district && district.trim() ? district.trim() : null,
        budget: q.ask_budget ? budget : null,
        consent: true,
        website: honeypot || null,
      }));
      onSent(result);
    } catch (e) {
      setError(message(e));
    } finally {
      setSending(false);
    }
  };

  const blocked = screen === "pick" ? !canContinue : screen === "about" ? districtBlocked || sending : false;

  return (
    <footer className="s-foot" inert={inert}>
      <div className="s-foot__msg">
        {screen === "pick" ? (
          <>
            {canContinue ? <Icon name="check" size="sm" /> : null}
            {progressText}
          </>
        ) : null}
        {error ? (
          <span role="alert" style={{ color: "var(--danger)", display: "flex", gap: 6, alignItems: "center" }}>
            <Icon name="alert" size="sm" />
            {error}
          </span>
        ) : null}
      </div>
      <div className="s-foot__row">
        {screen !== "consent" ? (
          <button className="btn btn--ghost" type="button" onClick={onBack} disabled={sending}>
            Back
          </button>
        ) : null}
        <button
          className="btn btn--primary btn--lg grow"
          type="button"
          disabled={blocked}
          aria-disabled={blocked}
          onClick={screen === "about" ? () => void send() : onNext}
        >
          {screen === "consent" ? (
            "Start"
          ) : screen === "pick" ? (
            "Continue"
          ) : sending ? (
            <>
              <span className="spin pending-spin" aria-hidden="true" />
              Sending
            </>
          ) : error ? (
            <>
              <Icon name="refresh" />
              Try again
            </>
          ) : (
            <>
              <Icon name="send" />
              Send my picks
            </>
          )}
        </button>
      </div>
      <p className="s-foot__fine">
        {screen === "consent"
          ? "Nothing is saved until you press Send."
          : screen === "pick"
            ? "Nothing is saved until you press Send."
            : "By pressing Send you agree to the notice. You can’t be identified from this."}
      </p>
    </footer>
  );
}

// ---- removal ----------------------------------------------------------------------------------------------------
function RemoveSheet({ open, initialCode, onClose }: { open: boolean; initialCode: string; onClose: () => void }) {
  const [code, setCode] = useState("");
  const [state, setState] = useState<{ s: "idle" | "working" | "done" | "missing" | "error"; text?: string }>({ s: "idle" });

  // Start fresh each time the sheet opens (adjusting state while rendering, as React recommends over an effect).
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setCode(initialCode);
      setState({ s: "idle" });
    }
  }

  const remove = async () => {
    const receipt = code.trim();
    if (receipt.length < 10) {
      setState({ s: "error", text: "Enter the whole receipt code." });
      return;
    }
    setState({ s: "working" });
    try {
      const result = await api<{ removed: boolean }>("/public/response/delete", { method: "POST", body: { receipt } });
      setState(result.removed ? { s: "done" } : { s: "missing" });
    } catch (error) {
      setState({ s: "error", text: message(error) });
    }
  };

  return (
    <Sheet open={open} onClose={onClose} title="Remove your answers?" role="alertdialog">
      {state.s === "done" ? (
        <>
          <div className="banner" data-tone="ok" role="status">
            <Icon name="check" />
            <div className="banner__body">
              <strong>Removed.</strong>
              Your answers are gone and will not be counted.
            </div>
          </div>
          <button className="btn grow" type="button" onClick={onClose}>
            Close
          </button>
        </>
      ) : (
        <>
          <p>
            Enter the receipt code you were given after sending. This can&rsquo;t be undone.
          </p>
          <div className="field">
            <label htmlFor="receipt-in">Receipt code</label>
            <input
              className="input"
              id="receipt-in"
              type="text"
              autoComplete="off"
              autoCapitalize="off"
              spellCheck={false}
              maxLength={100}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              aria-invalid={state.s === "missing" || state.s === "error"}
            />
            {state.s === "missing" ? (
              <p className="field__err" role="alert">
                <Icon name="alert" size="sm" />
                We couldn&rsquo;t find that code. It may already be removed, or have a typo.
              </p>
            ) : null}
            {state.s === "error" ? (
              <p className="field__err" role="alert">
                <Icon name="alert" size="sm" />
                {state.text}
              </p>
            ) : null}
          </div>
          <div className="row row--wrap">
            <button className="btn btn--danger grow" type="button" onClick={() => void remove()} disabled={state.s === "working"}>
              {state.s === "working" ? "Removing…" : "Remove my answers"}
            </button>
            <button className="btn grow" type="button" onClick={onClose}>
              Keep them
            </button>
          </div>
        </>
      )}
    </Sheet>
  );
}
