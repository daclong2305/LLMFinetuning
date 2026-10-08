# Progress — 2026-10-07-vietnamese-experiment-system.md

Baseline: 26 unittest tests pass. No Git repository, so worktree/commit steps do not apply; existing files retained in place.
Environment: Python 3.10; RTX 3060 Laptop 6GB driver 546.30; no torch/transformers/peft/datasets; no OPENAI_API_KEY in current process. User will configure key locally.
Design approval: user explicitly requested implementation of the reviewed design. Proceed with necessary reversible work; no repeated design approval.
Pre-flight: shared interfaces fixed in spec; agent ownership prevents overlapping file writes.
Ruling: core uses stdlib and optional isolated training dependencies. No system driver modifications. Missing trained checkpoint remains unavailable.

Task 1: official source downloaded; counts train6831/dev954/test1908, database-disjoint. Final structural audit with SQLite compilation guard: 9149/9693 supported (6453 train, 941 dev, 1755 test), 544 unavailable labelled. Optional validated TS/VES execution paths implemented; real SQLite/suites are absent.
Task 2: registry, real Responses/Ollama adapters, SFT/QLoRA completion-only training/merge/register workflow completed. Data export actual6458train/941dev, exclusions373/13 with provenance. No actual optimizer steps, dependencies absent.
Task 3: dashboard completed and browser inspected. Model states and missing metrics honest; original retail demo preserved at /legacy.
Task 4: shared pipeline/benchmark/local API implemented; initial 80 whole tests pass. Root added Vietnamese SQL execution-policy regression RED->GREEN after live Qwen returned unquoted multiword names and evaluator/preview diverged.
Live smoke: browser C0 on dev:00000 called actual qwen2.5-coder:3b, 359 input/45 outputtokens, 1 call, ~9.92s. SQL structuralEM/CM1.0; no data-filledSQLite so EX/TS/VES unavailable. Before root normalization fix status syntaxerror; supersede this check with final verified run.
Ruling: training exports exclude schema-invalid targets without modifying source evaluation labels; raw and retained counts kept. Cost if wrong: some valid SQL forms may be excluded, exclusions auditable.

Final integration: independent system/metric reviews completed. Regression fixes cover OR parsing, malformed SQL, SQLite preview normalization, static snapshot/WAL integrity, projection/order semantics, eligible timeout denominators, retained partial usage, persisted owner identity/cancellation and CSP chart rendering.
Verification: final full suite 108 tests passed in 10.337s; Node syntax check passed. Reproduced Windows unread rejected POST body reset; bounded discard regression RED->GREEN, 100/100 actual requests returned 403. Browser resumed successfully, benchmark chart widths applied under CSP, no browser console warnings/errors. CSV/JSON and HTTP export verified. Default server restarted on 8765. Screenshot and full evidence in reports/experiment-verification.md.
Real pilot: run 0bb5888651e8400aa8a86eaabe32954f, dev:00000/dev:00001, qwen_base c0/full, 4/4 records completed. EM/CM=1 on both configurations; c0 2 calls, 729/112 tokens, p50 6272.985ms; full 7 calls (1 repair), 5259/210 tokens, p50 15983.645ms. Local API cost 0 excludes hardware/training. EX/TS/VES unavailable. This is a smoke pilot, not a full comparative benchmark.
External prerequisites: user-configured GPT credential, actual trained Qwen checkpoint, compatible data-filled SQLite and reviewed TS/VES assets. Training workflow/data export ready; no optimizer steps claimed.
