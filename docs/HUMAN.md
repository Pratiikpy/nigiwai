# Needs a human

Requests that only Prateek can answer or authorise. Work continues on everything unrelated. Silence is not approval. Newest last.

| # | Date | Request | Why it matters | Status |
|---|---|---|---|---|
| H1 | 2026-10-23 | May the API read the Anthropic key in `~/.secrets/anthropic-promo.env` for the LLM features (Ask agent, onboarding, tribe naming, the AI-alone panel)? | The goal authorises only the Qloo key file. Without an LLM key those features run on deterministic templates and the Ask agent reports itself unavailable. | OPEN. Everything else proceeds. The adapter is built and tested against a local test server. |
| H2 | 2026-10-23 | Approve creating hosting, database and identity accounts (Cloud Run, Neon, Upstash, Clerk, Cloudflare), a domain, and a public deploy. | Needed only to launch. The product is built to run from containers without them. | OPEN. Not needed to continue. |
| H3 | 2026-10-23 | Review the Qloo transport default (decision D5): harness primary, REST for calls that need `warnings` or rate-limit headers. Flip the default to REST? | The harness CLI drops `warnings` and headers (verified). | OPEN. Both transports are built and selectable with `NIGIWAI_QLOO_TRANSPORT`. |
| H4 | 2026-10-23 | Optional: a free Last.fm key saved to `~/.secrets/lastfm.env`. | Lets us measure relevance of obscure-act suggestions with an outside source. | OPEN. Optional. |
| H5 | 2026-10-23 | Qloo's written answer on terms (paid product, caching, display), per research/QLOO_QUESTIONS.md. | Needed for a paid launch, not for the demo. | OPEN. Contacting Qloo is restricted. |
