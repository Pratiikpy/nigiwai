"use client";

import { useState } from "react";
import { Icon } from "@/components/Icon";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { ApiError, api, type Business, type Location } from "@/lib/api";
import { useSession } from "@/lib/session";
import { useVenue } from "@/lib/venue";

const TYPES: [string, string][] = [
  ["bar", "Bar"],
  ["live_music_venue", "Live music venue"],
  ["restaurant", "Restaurant"],
  ["cafe", "Café"],
  ["brewery", "Brewery"],
  ["hotel_bar", "Hotel bar"],
  ["festival", "Festival"],
  ["promoter", "Promoter"],
  ["shop", "Shop"],
  ["other", "Other"],
];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function VenuePage() {
  const { venue, error } = useVenue();
  if (error) return <Notice tone="error">{error}</Notice>;
  if (!venue) return <Loading />;
  return <VenueForm business={venue.business} location={venue.location} />;
}

function VenueForm({ business, location }: { business: Business | null; location: Location | null }) {
  const { reload, tenantPath, canWrite } = useVenue();
  const { state } = useSession();
  const [name, setName] = useState(business?.name ?? (state.status === "ready" ? state.tenant.name : ""));
  const [type, setType] = useState(business?.type ?? "bar");
  const [currency, setCurrency] = useState(business?.currency ?? "USD");
  const [locName, setLocName] = useState(location?.name ?? "Main room");
  const [address, setAddress] = useState(location?.address ?? "");
  const [lat, setLat] = useState(location?.lat?.toString() ?? "");
  const [lon, setLon] = useState(location?.lon?.toString() ?? "");
  const [radius, setRadius] = useState((location?.radius_m ?? 800).toString());
  const [timezone, setTimezone] = useState(location?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone ?? "UTC");
  const [price, setPrice] = useState(location?.price_level?.toString() ?? "");
  const [capacity, setCapacity] = useState(location?.capacity?.toString() ?? "");
  const [curfew, setCurfew] = useState(location?.curfew ?? "");
  const [genres, setGenres] = useState((location?.excluded_genres ?? []).join(", "));
  const [nights, setNights] = useState<number[]>(location?.show_nights ?? []);
  const [busy, setBusy] = useState(false);
  const [locating, setLocating] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const locate = () => {
    if (!navigator.geolocation) {
      setProblem("This browser can't share its location. Type the coordinates instead.");
      return;
    }
    setLocating(true);
    setProblem(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLat(pos.coords.latitude.toFixed(6));
        setLon(pos.coords.longitude.toFixed(6));
        setLocating(false);
      },
      () => {
        setLocating(false);
        setProblem("We couldn't get your location. Allow it in the browser, or type the coordinates instead.");
      },
      { enableHighAccuracy: true, timeout: 12_000 },
    );
  };

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setProblem(null);
    setSaved(false);
    const latNum = lat.trim() === "" ? null : Number(lat);
    const lonNum = lon.trim() === "" ? null : Number(lon);
    if ((latNum === null) !== (lonNum === null)) {
      setProblem("Give both latitude and longitude, or leave both empty.");
      return;
    }
    if ((latNum !== null && !Number.isFinite(latNum)) || (lonNum !== null && !Number.isFinite(lonNum))) {
      setProblem("Latitude and longitude must be numbers, for example 51.5072 and -0.1276.");
      return;
    }
    const body = {
      name: locName,
      address: address.trim() || null,
      lat: latNum,
      lon: lonNum,
      radius_m: Number(radius),
      timezone,
      price_level: price ? Number(price) : null,
      capacity: capacity ? Number(capacity) : null,
      curfew: curfew.trim() || null,
      excluded_genres: genres
        .split(",")
        .map((g) => g.trim())
        .filter(Boolean),
      show_nights: nights,
    };
    setBusy(true);
    try {
      const biz = business
        ? await api<Business>(`${tenantPath}/businesses/${business.id}`, { method: "PUT", body: { name, type, currency } })
        : await api<Business>(`${tenantPath}/businesses`, { method: "POST", body: { name, type, currency } });
      if (location) await api<Location>(`${tenantPath}/locations/${location.id}`, { method: "PUT", body });
      else await api<Location>(`${tenantPath}/businesses/${biz.id}/locations`, { method: "POST", body });
      await reload();
      setSaved(true);
    } catch (e) {
      setProblem(e instanceof ApiError ? e.detail : "We couldn't save that. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHead
        title="Your venue"
        lead="Where guests scan, and what you run. Coordinates are only used to find places near you."
      />
      {!canWrite ? <Notice tone="warn">Your role can look at this page but not change it.</Notice> : null}
      <form className="form" onSubmit={save} noValidate>
        <fieldset className="card stack" disabled={!canWrite || busy}>
          <legend className="card__title">The business</legend>
          <div className="field">
            <label htmlFor="b-name">Name</label>
            <input className="input" id="b-name" required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="grid-2">
            <div className="field">
              <label htmlFor="b-type">Type</label>
              <select className="input" id="b-type" value={type} onChange={(e) => setType(e.target.value)}>
                {TYPES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="b-cur">Currency</label>
              <input
                className="input"
                id="b-cur"
                maxLength={3}
                minLength={3}
                value={currency}
                onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                aria-describedby="b-cur-h"
              />
              <p className="field__hint" id="b-cur-h">
                Three letters, for example USD, GBP, EUR.
              </p>
            </div>
          </div>
        </fieldset>

        <fieldset className="card stack" disabled={!canWrite || busy}>
          <legend className="card__title">The place</legend>
          <div className="field">
            <label htmlFor="l-name">Room or site name</label>
            <input className="input" id="l-name" required maxLength={120} value={locName} onChange={(e) => setLocName(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="l-address">Address (optional)</label>
            <input className="input" id="l-address" maxLength={300} autoComplete="street-address" value={address} onChange={(e) => setAddress(e.target.value)} />
          </div>
          <div className="grid-2">
            <div className="field">
              <label htmlFor="l-lat">Latitude</label>
              <input className="input" id="l-lat" inputMode="decimal" value={lat} onChange={(e) => setLat(e.target.value)} placeholder="51.5072" />
            </div>
            <div className="field">
              <label htmlFor="l-lon">Longitude</label>
              <input className="input" id="l-lon" inputMode="decimal" value={lon} onChange={(e) => setLon(e.target.value)} placeholder="-0.1276" />
            </div>
          </div>
          <div>
            <button className="btn btn--sm" type="button" onClick={locate} disabled={locating}>
              <Icon name="pin" size="sm" />
              {locating ? "Finding you…" : "Use this device's location"}
            </button>
            <p className="field__hint" style={{ marginTop: "var(--s-2)" }}>
              Stand in the venue and use this, or type the coordinates. The location is read once and never stored on
              this device.
            </p>
          </div>
          <div className="grid-2">
            <div className="field">
              <label htmlFor="l-radius">Area that counts as nearby (metres)</label>
              <input className="input" id="l-radius" type="number" min={50} max={50000} step={50} value={radius} onChange={(e) => setRadius(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="l-tz">Time zone</label>
              <input className="input" id="l-tz" value={timezone} onChange={(e) => setTimezone(e.target.value)} aria-describedby="l-tz-h" />
              <p className="field__hint" id="l-tz-h">
                For example Europe/London. Used to record the day and hour of each answer in your local time.
              </p>
            </div>
          </div>
        </fieldset>

        <fieldset className="card stack" disabled={!canWrite || busy}>
          <legend className="card__title">What you run (optional)</legend>
          <div className="grid-2">
            <div className="field">
              <label htmlFor="l-price">Price level</label>
              <select className="input" id="l-price" value={price} onChange={(e) => setPrice(e.target.value)}>
                <option value="">Not set</option>
                <option value="1">$ Easy on the wallet</option>
                <option value="2">$$ Somewhere in the middle</option>
                <option value="3">$$$ Treat yourself</option>
                <option value="4">$$$$ Special occasion</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="l-cap">Capacity</label>
              <input className="input" id="l-cap" type="number" min={1} max={200000} value={capacity} onChange={(e) => setCapacity(e.target.value)} />
            </div>
          </div>
          <div className="field">
            <label htmlFor="l-curfew">Curfew</label>
            <input className="input" id="l-curfew" maxLength={20} placeholder="23:00" value={curfew} onChange={(e) => setCurfew(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="l-genres">Genres you won&rsquo;t book</label>
            <input className="input" id="l-genres" value={genres} onChange={(e) => setGenres(e.target.value)} placeholder="metal, drill" />
            <p className="field__hint">Separate with commas.</p>
          </div>
          <fieldset className="qset">
            <legend>Show nights</legend>
            <div className="chips" role="group" aria-label="Show nights">
              {DAYS.map((day, i) => (
                <button
                  key={day}
                  className="chipbtn"
                  type="button"
                  aria-pressed={nights.includes(i)}
                  onClick={() => setNights((n) => (n.includes(i) ? n.filter((x) => x !== i) : [...n, i].sort()))}
                >
                  {day}
                </button>
              ))}
            </div>
          </fieldset>
        </fieldset>

        {problem ? <Notice tone="error">{problem}</Notice> : null}
        {saved ? <Notice tone="ok">Saved.</Notice> : null}
        {canWrite ? (
          <div>
            <button className="btn btn--primary btn--lg" type="submit" disabled={busy}>
              {busy ? "Saving…" : "Save"}
            </button>
          </div>
        ) : null}
      </form>
    </>
  );
}
