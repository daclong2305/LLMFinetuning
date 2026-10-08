Vendored from https://github.com/taoyds/spider at revision
b7b5b8c890cd30e35427348bb9eb8c6d1350ca7c. Original evaluation.py and
process_sql.py copyright their upstream authors; Apache-2.0 LICENSE included.

Local changes: relative imports; a dependency-free SQL lexer replacing NLTK;
reject trailing unparsed tokens; accept output aliases and signed numeric
values. The application canonicalizes Vietnamese
identifiers before parsing. Structural scoring keeps Spider's official
DISABLE_VALUE=True and DISABLE_DISTINCT=True policy and FK equivalence.
CM is the macro mean of active component F1 values (including the auxiliary
no-aggregation/no-operator components), not an official Spider leaderboard
metric. Full-result execution comparison is an independent local adapter,
not upstream Spider's legacy execution scorer.

Additional local fixes: condition-value parsing stops at both AND and OR and
rejects unconsumed right-hand-side tokens. The adapter compiles SQL against a
schema-only SQLite connection before structural scoring, rejecting malformed
targets rather than awarding scores for partially parsed SQL. Unsupported gold
targets remain unavailable with explicit coverage and audit reasons.

The execution adapter preserves duplicate rows and requires row order only for
outermost ORDER BY. It accepts one consistent global projection permutation;
independent per-row permutations are not accepted. Static database snapshots
reject active WAL/journal files and changed hashes before and after evaluation.
Prediction errors/timeouts score zero when the gold and assets are eligible.

Optional adapted local test-suite accuracy (TS) requires
`<dataset-root>/test-suite-manifest.json`:

```json
{
  "version": 1,
  "dataset_fingerprint": "the current DatasetStore.summary().fingerprint",
  "provenance": {"source": "suite origin", "description": "how the states were produced and reviewed"},
  "files": [
    {"db_id": "database id", "path": "test-suite/db/state1.sqlite", "sha256": "64 lowercase hex characters"},
    {"db_id": "database id", "path": "test-suite/db/state2.sqlite", "sha256": "64 lowercase hex characters"}
  ]
}
```

Paths must resolve to files beneath the private dataset root. Fingerprint,
provenance, file hashes, schema compatibility, nonempty data and complete gold
execution are checked. At least two distinct file hashes AND actual table-data
states are required per database; different metadata for identical rows does
not qualify. TS is one only when the prediction matches gold on every validated
state, preserving duplicates and gold ORDER BY row order. This adapter validates
asset integrity and execution; provenance is supplied by the researcher and
does not itself certify suite completeness. Missing/invalid assets yield null
with reasons. No benchmark suite is synthesized by the application.

Optional adapted local VES requires `<dataset-root>/evaluation-options.json`:

```json
{"ves_repeats": 100, "ves_budget_s": 60}
```

The presence of an integer ves_repeats from 100 through 1000 explicitly enables
timing; `ves_enabled: false` disables it. A compatible data-filled base database,
complete gold audit and available EX are required. Incorrect predictions score
zero. Correct predictions execute all requested interleaved gold/prediction
pairs, alternating their order, and score mean(sqrt(gold_ms/prediction_ms)).
Every repeated result must be complete and stable. Timings include connection,
read-only authorization, execution and full fetching; they are SQLite wall-clock
measurements and are affected by caches and other local activity. The default
total timing budget is 60 seconds (configurable up to 600); incomplete runs,
failed queries and timings below resolution yield null, retaining pair counts.
This adapted local statistic is not an official ViText2SQL or BIRD leaderboard
score and is not GPU/model generation latency.

DatasetStore.summary() exposes `test_suite`, `evaluation_options` and
`metric_assets_fingerprint`. Reproducibility manifests must preserve this
separate metric fingerprint; optional assets/settings do not change the base
dataset fingerprint referenced by the suite manifest. VES/TS remain null for
the acquired official source until the necessary real assets are supplied.
