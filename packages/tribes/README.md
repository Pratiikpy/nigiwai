# nigiwai-tribes

Groups a venue's guests into soft "tribes" from the Qloo tags of what they picked. Pure numerical code: no network, no database, no Qloo calls. It is built from the behaviour measured in proof tests D and G (see docs/DECISIONS.md D12) and states, on every result, how stable the groups are against two null models.

- `build.py` turns picks into a respondent-by-tag matrix.
- `model.py` fits soft NMF and projects a new respondent onto it.
- `stability.py` measures bootstrap stability and the two nulls.
- `naming.py` finds each tribe's top items and lift tags with intervals and builds a name only from those.
- `rhythm.py`, `signature.py` count when and which category pairs.
- `pipeline.py` runs it all and returns a JSON-serialisable result with an unlock state.
