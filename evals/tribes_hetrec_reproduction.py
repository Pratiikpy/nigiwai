"""Reproduce proof D's real-data stability numbers with the production stability code.

Proof D measured bootstrap stability of soft NMF (K = 3) on respondents built from the GroupLens HetRec 2011
Last.fm 2k data. That data is for research use only and lives outside this repository; this script never copies it.
It imports the proof's own preprocessing from the research folder to build the same respondent matrix, then runs
`nigiwai_tribes.stability` on it. If the numbers match, the production implementation measures what the proof measured.

    uv run python evals/tribes_hetrec_reproduction.py --proof-d-code <research>/test-results/proof-D/code [--crowds 30] [--bootstrap 200]

Reference numbers (proof D, `out/real_stability.csv`, soft NMF, K = 3, free picks, 30 crowds per N, B = 200):
real 0.506 / 0.561 / 0.586 / 0.623 at N = 30 / 60 / 100 / 200;
permuted-column null 0.226 / 0.274 / 0.342 / 0.436; random-pick null 0.273 / 0.345 / 0.439 / 0.580.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from nigiwai_tribes import TribesConfig
from nigiwai_tribes.stability import bootstrap_stability

REFERENCE = {
    "real": {30: 0.506, 60: 0.561, 100: 0.586, 200: 0.623},
    "permuted": {30: 0.226, 60: 0.274, 100: 0.342, 200: 0.436},
    "random_picks": {30: 0.273, 60: 0.345, 100: 0.439, 200: 0.580},
}
TOLERANCE = (
    0.03  # a few crowds' worth of sampling noise: the proof's own 95% intervals were about +-0.03
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--proof-d-code", required=True, type=Path)
    ap.add_argument("--crowds", type=int, default=30)
    ap.add_argument("--bootstrap", type=int, default=200)
    ap.add_argument("--out", type=Path, default=Path("evals/out/tribes_hetrec.json"))
    args = ap.parse_args()

    sys.path.insert(0, str(args.proof_d_code))
    import common as d  # the proof's preprocessing, unchanged

    print(
        "building the respondent matrix from the HetRec data (proof D preprocessing)...", flush=True
    )
    p = d.build_all(True)
    picks, stats = d.user_picks(p)
    users = sorted(u for u, x in picks.items() if x["free"] is not None and x["guided"] is not None)
    x_free = np.array([d.respondent_counts(picks[u]["free"]) for u in users])
    idf = p["idf"]
    cat = np.where(p["tot"] >= 20)[0]
    a_cat = d.l1(p["A"][cat])
    pop_cat = np.maximum(p["pop"][cat], 1.0)
    print(f"{len(users)} respondents, {x_free.shape[1]} tags, {stats}", flush=True)

    cfg = TribesConfig(bootstrap=args.bootstrap)
    results: dict[str, dict[int, list[float]]] = {"real": {}, "permuted": {}, "random_picks": {}}
    t0 = time.time()
    for n in (30, 60, 100, 200):
        for kind in results:
            results[kind][n] = []
        for c in range(args.crowds):
            idx = np.sort(d.rng_for("real_crowd", n, c).choice(len(users), size=n, replace=False))
            feats = d.features(x_free[idx], idf)
            rng = np.random.default_rng(np.random.SeedSequence([cfg.seed, n, c]))
            results["real"][n].append(bootstrap_stability(feats, 3, cfg, rng)[0])

            rng_a = d.rng_for("nullA", n, c)
            xn = feats.copy()
            for j in range(xn.shape[1]):
                xn[:, j] = rng_a.permutation(xn[:, j])
            results["permuted"][n].append(bootstrap_stability(d.l2rows(xn), 3, cfg, rng)[0])

            rng_b = d.rng_for("nullB", n, c)
            prob = pop_cat / pop_cat.sum()
            xb = np.zeros((n, x_free.shape[1]))
            for r in range(n):
                items = rng_b.choice(len(cat), size=5, replace=False, p=prob)
                xb[r] = a_cat[items].sum(0)
            results["random_picks"][n].append(
                bootstrap_stability(d.features(xb, idf), 3, cfg, rng)[0]
            )
        print(f"N={n} done, {time.time() - t0:.0f}s", flush=True)

    ok = True
    table = {}
    print(f"\n{'':14}{'N':>5}{'ours':>9}{'proof D':>9}{'diff':>8}")
    for kind, by_n in results.items():
        for n, vals in by_n.items():
            ours = float(np.mean(vals))
            ref = REFERENCE[kind][n]
            diff = ours - ref
            good = abs(diff) <= TOLERANCE
            ok &= good
            table[f"{kind}@{n}"] = {
                "ours": round(ours, 3),
                "proof_d": ref,
                "diff": round(diff, 3),
                "within": good,
            }
            print(
                f"{kind:14}{n:>5}{ours:>9.3f}{ref:>9.3f}{diff:>+8.3f}  {'ok' if good else 'OUT OF TOLERANCE'}"
            )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "tolerance": TOLERANCE,
                "crowds": args.crowds,
                "bootstrap": args.bootstrap,
                "table": table,
            },
            indent=1,
        )
    )
    print("\nREPRODUCED" if ok else "\nNOT REPRODUCED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
