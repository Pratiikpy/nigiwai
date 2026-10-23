"use client";

import Link from "next/link";
import { useState } from "react";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { ApiError, api, type PickerType, type Questions, type Survey } from "@/lib/api";
import { CATEGORIES } from "@/lib/survey";
import { useVenue } from "@/lib/venue";

const ALL_TYPES = Object.keys(CATEGORIES) as PickerType[];
const DEFAULTS: Questions = {
  min_picks: 3,
  max_picks: 5,
  ask_age_band: true,
  ask_district: true,
  ask_budget: true,
  picker_types: ["artist", "tv_show", "movie", "brand", "podcast", "videogame", "book"],
};

export default function SurveyPage() {
  const { venue, error } = useVenue();
  if (error) return <Notice tone="error">{error}</Notice>;
  if (!venue) return <Loading />;
  if (!venue.business) {
    return (
      <>
        <PageHead title="Survey" />
        <Notice tone="warn">
          Describe your venue first. <Link href="/app/venue">Go to your venue</Link>
        </Notice>
      </>
    );
  }
  return <SurveyForm businessId={venue.business.id} survey={venue.survey} />;
}

function SurveyForm({ businessId, survey }: { businessId: string; survey: Survey | null }) {
  const { tenantPath, reload, canWrite, venue } = useVenue();
  const initial = survey?.questions ?? DEFAULTS;
  const [min, setMin] = useState(initial.min_picks);
  const [max, setMax] = useState(initial.max_picks);
  const [types, setTypes] = useState<PickerType[]>(initial.picker_types);
  const [age, setAge] = useState(initial.ask_age_band);
  const [district, setDistrict] = useState(initial.ask_district);
  const [budget, setBudget] = useState(initial.ask_budget);
  const [rewardTitle, setRewardTitle] = useState(survey?.reward?.title ?? "");
  const [rewardDetail, setRewardDetail] = useState(survey?.reward?.detail ?? "");
  const [busy, setBusy] = useState<"save" | "publish" | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const firstQr = venue?.qrPoints.find((q) => q.status === "active" && q.url);
  const invalid = min > max ? "The minimum can't be more than the maximum." : types.length === 0 ? "Choose at least one kind of pick." : null;

  const submit = async (publish: boolean) => {
    if (invalid || busy) return;
    setBusy(publish ? "publish" : "save");
    setProblem(null);
    setDone(null);
    try {
      const body = {
        questions: {
          min_picks: min,
          max_picks: max,
          ask_age_band: age,
          ask_district: district,
          ask_budget: budget,
          picker_types: types,
        },
        reward: rewardTitle.trim() ? { title: rewardTitle.trim(), detail: rewardDetail.trim() } : null,
        publish,
      };
      const saved = await api<Survey>(`${tenantPath}/businesses/${businessId}/survey`, { method: "PUT", body });
      await reload();
      setDone(publish ? `Published as version ${saved.version}. Guests who scan from now on see it.` : `Saved as a draft (version ${saved.version}). It is not live yet.`);
    } catch (e) {
      setProblem(e instanceof ApiError ? e.detail : "We couldn't save that. Please try again.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <PageHead
        title="Survey"
        lead="What guests are asked after they scan. Every save is a new version, so each answer keeps the questions the guest actually saw."
      />
      {survey ? (
        <p>
          <span className="pill" data-tone={survey.status === "published" ? undefined : "muted"}>
            {survey.status === "published" ? "Live" : survey.status === "draft" ? "Draft" : "Archived"} · version {survey.version}
          </span>
          {survey.status === "draft" ? <span className="meta"> Guests still see the last published version, if there is one.</span> : null}
        </p>
      ) : (
        <Notice tone="sample">No survey yet. The defaults below are a good start. Publish it when you are ready.</Notice>
      )}

      <form className="form" onSubmit={(e) => e.preventDefault()} noValidate>
        <fieldset className="card stack" disabled={!canWrite || busy !== null}>
          <legend className="card__title">Picks</legend>
          <div className="grid-2">
            <div className="field">
              <label htmlFor="s-min">At least</label>
              <select className="input" id="s-min" value={min} onChange={(e) => setMin(Number(e.target.value))}>
                {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="s-max">At most</label>
              <select className="input" id="s-max" value={max} onChange={(e) => setMax(Number(e.target.value))}>
                {Array.from({ length: 8 }, (_, i) => i + 3).map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <p className="field__hint">Three to five is the sweet spot: enough to tell guests apart, quick to answer.</p>
          <fieldset className="qset">
            <legend>Guests can pick</legend>
            <div className="toggle-list">
              {ALL_TYPES.map((t) => (
                <label className="check" key={t}>
                  <input
                    type="checkbox"
                    checked={types.includes(t)}
                    onChange={(e) => setTypes((cur) => (e.target.checked ? [...cur, t] : cur.filter((x) => x !== t)))}
                  />
                  <span>{CATEGORIES[t].label}</span>
                </label>
              ))}
            </div>
          </fieldset>
        </fieldset>

        <fieldset className="card stack" disabled={!canWrite || busy !== null}>
          <legend className="card__title">Optional questions</legend>
          <p className="muted">Each is optional for the guest. You only ever see answers as group totals, for groups of 10 or more.</p>
          <div className="toggle-list">
            <label className="check">
              <input type="checkbox" checked={age} onChange={(e) => setAge(e.target.checked)} />
              <span>
                <strong>Age range</strong>
                <span className="meta">Six bands from 18–24 to 65+.</span>
              </span>
            </label>
            <label className="check">
              <input type="checkbox" checked={district} onChange={(e) => setDistrict(e.target.checked)} />
              <span>
                <strong>Area</strong>
                <span className="meta">A district or neighbourhood, never an address.</span>
              </span>
            </label>
            <label className="check">
              <input type="checkbox" checked={budget} onChange={(e) => setBudget(e.target.checked)} />
              <span>
                <strong>Usual spend</strong>
                <span className="meta">From $ to $$$$.</span>
              </span>
            </label>
          </div>
        </fieldset>

        <fieldset className="card stack" disabled={!canWrite || busy !== null}>
          <legend className="card__title">A thank-you (optional)</legend>
          <div className="field">
            <label htmlFor="r-title">What guests get</label>
            <input className="input" id="r-title" maxLength={80} placeholder="A free coffee" value={rewardTitle} onChange={(e) => setRewardTitle(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="r-detail">How to claim it</label>
            <input className="input" id="r-detail" maxLength={200} placeholder="Show this screen at the counter." value={rewardDetail} onChange={(e) => setRewardDetail(e.target.value)} />
          </div>
        </fieldset>

        {invalid ? <Notice tone="warn">{invalid}</Notice> : null}
        {problem ? <Notice tone="error">{problem}</Notice> : null}
        {done ? <Notice tone="ok">{done}</Notice> : null}

        {canWrite ? (
          <div className="row row--wrap">
            <button className="btn btn--primary btn--lg" type="button" disabled={!!invalid || busy !== null} onClick={() => void submit(true)}>
              {busy === "publish" ? "Publishing…" : "Publish"}
            </button>
            <button className="btn btn--lg" type="button" disabled={!!invalid || busy !== null} onClick={() => void submit(false)}>
              {busy === "save" ? "Saving…" : "Save as draft"}
            </button>
            {firstQr?.url ? (
              <a className="btn btn--lg btn--ghost" href={firstQr.url.replace(/^https?:\/\/[^/]+/, "")} target="_blank" rel="noreferrer">
                Open the live survey
              </a>
            ) : null}
          </div>
        ) : null}
      </form>
    </>
  );
}
