# nigiwai-fit

The Fit Verdict (PRD M19, ARCHITECTURE 5.3). Pure code: no network, no database. The service layer asks Qloo one question per
crowd group and hands the answers here; this package turns them into a score anyone can recompute.

## What it does

For a candidate (an act) and a crowd split into groups:

1. **Group fit** `f_t` in [0, 1]: the candidate's percentile rank among the reference entities Qloo returned for that group's
   seeds in the same call (raw affinity is not comparable across signal sets, so only the rank within one call is used; ties
   count half). A group with fewer than 8 returned references is left out, and so is a group for which Qloo returned no
   affinity for the candidate.
2. **Shares** `s_t`: each scored group's share of the crowd, renormalised over the scored groups.
3. **Risk** `R = sum_t s_t * max(0, 0.5 - f_t) * 2`: the weight of the crowd the candidate fits poorly.
4. **Peer evidence** `P` in [0, 1], optional. When it is absent its weight goes to the group fit and the result says so.
5. **Score** `round(100 * (0.8 * sum_t s_t f_t + 0.2 * P) * (1 - 0.5 * R))`, with the weights stored and versioned.
6. **Band**: the 10th to 90th percentile over 200 bootstrap draws (references resampled within each group; crowd members
   resampled when their memberships are supplied). The generator is seeded from the input hash, so the band is reproducible.
7. **No number** when the crowd is too thin, when a constraint fails, or when groups making up less than 60% of the crowd could
   not be scored. The result then says why.

The same inputs always give the same output, including the band. Wording is "fit": never success, revenue or probability. The
weights are a starting design and **NOT VERIFIED** against outcomes.
