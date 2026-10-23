# nigiwai-qloo-guard

Every call to the Qloo Taste AI API passes through this package. It turns the 18 trap classes and the extra rules found in testing into code, so a misspelled parameter, a person seed, a swapped coordinate or an item that Qloo never returned cannot reach a screen.

What it does, in pipeline order: typed request, rule checks, budget reservation, private cache, single-flight, rate limit, transport (harness CLI, REST or replay), result classification and post-rules, persistence, trace.

Qloo response data is never committed, logged or published. Tests use invented fixtures; recorded real responses live only in a git-ignored private folder.

See `docs/QLOO_USAGE.md` in the repository root for every endpoint used and why, and `docs/DECISIONS.md` (D5) for the transport policy.
