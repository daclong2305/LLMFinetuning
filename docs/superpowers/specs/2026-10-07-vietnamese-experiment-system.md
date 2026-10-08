# Vietnamese Text-to-SQL experiment system

The user approved implementing the reviewed experiment design. Build in the existing directory; it is not a Git repository. Preserve the original retail demo at `/legacy`. The main page is a Vietnamese research dashboard.

## Scope

- Official VinAIResearch/ViText2SQL syllable-level data, revision e759141d891feb794bb9a9fb912d544b25583b3c; immutable file hashes and database-disjoint split audit. Private downloaded data lives under `.runtime/datasets/vitext2sql` and is not redistributed.
- Qwen2.5-Coder base, an independently trained Qwen checkpoint, and fixed GPT `gpt-4.1-mini-2025-04-14`. Training is an explicit SFT/QLoRA workflow and artifact; never relabel the base as trained. Missing keys, weights, training dependencies, SQLite databases or test suites remain clearly unavailable, never simulated benchmark results.
- Shared C0 baseline, C1 decomposition via a bounded extra model call, C2 train-only lexical example retrieval plus schema linking preserving foreign-key bridges, C3 explicit compact SQL plan, C4 error-driven repair with max two repairs. Report these as representative implementations, not original DIN-SQL/DAIL-SQL.
- Structural EM and component F1 use an attributed Spider evaluator adapter. Full result execution comparison uses complete rows with a bound, preserves duplicates and ordering when required; UI previews cannot be used for correctness. EX requires compatible data-filled SQLite files and successful gold audit. Test-suite accuracy and VES are available only with validated input assets; null with reasons otherwise. Do not call preview success accuracy.
- Common immutable evaluation IDs, errors in denominator, separate metric coverage, per-difficulty statistics, Wilson intervals, latency p50/p95, SQL latency, complete token/call accounting, configured API cost with cached-input accounting, all-stage traces. Local API cost zero is labelled separately from hardware/training cost.
- Benchmark background jobs, reproducibility manifests, JSON/CSV export, cancellation, comparability validation. No gold/test rows in prompts or train retrieval. Test evaluation requires explicit final-evaluation mode; dev is the UI default.
- Extend providers through a registry adapter with `generate(messages)` returning standardized usage and errors; model IDs and inference settings are config, not hard-coded pipeline branches.

## Shared interfaces

`text2sql_demo/experiment/dataset.py`: `DatasetStore(root, database_dir=None)`, `.summary()`, `.samples(split, limit=None)`, `.get_sample(sample_id)`, `.schema(db_id)`, `.database_path(db_id)`. A sample is `{id,split,db_id,question,gold_sql,difficulty}`. Schema uses the existing `{table: {ddl,description,columns,foreign_keys}}` shape. `summary()` includes ready/state, fingerprint, revision, split counts, db counts, leakage audit, execution availability. Constructors do not start downloads.

`evaluation.py`: `evaluate_prediction(sql, sample, store, timeout_s=5)` returns `{em,cm,cm_components,ex,ts,ves,syntax_valid,execution_success,sql_latency_ms,gold_valid,unavailable_reasons}` with missing metrics null. Includes a full bounded read-only execution helper separate from legacy preview.

`backends.py`: `BackendRegistry(config)` with `.list_models()` and `.create(model_id)`. Config has `models` list of `{id,label,provider,model,...}`. Responses contain `{text,input_tokens,output_tokens,cached_input_tokens,cost_usd,model,response_id}`; `None` means unknown. Availability check never reveals credentials. Registry loads optional local `.env` without returning keys. Training artifacts validated for the fine-tuned model.

`pipeline.py`: `run_experiment(store, sample, backend, options, model_id=None)` where options are booleans c1/c2/c3/c4, few_shot_k=2 and max_repairs=2. Returns `{model_id,status,sql,error,execution,metrics,trace,options,model,...}`. Metrics include evaluation fields and `{latency_ms,input_tokens,output_tokens,cached_input_tokens,calls,cost_usd}`. Every model call accounted, including failures. Prompt construction receives no target gold SQL.

## HTTP contract

- `GET /api/experiment/info`: `{dataset,models,presets,metric_definitions,training}`.
- `GET /api/experiment/samples?split=dev&limit=30&offset=0&q=`: `{items,total,split}`; item includes id/question/db_id/difficulty.
- `GET /api/experiment/schema?db_id=`: `{db_id,schema}`.
- `POST /api/experiment/compare`: `{sample_id,model_ids,options}` or `{question,db_id,model_ids,options}`; returns `{id,sample,results,dataset_fingerprint}`. Free questions have null gold metrics.
- `POST /api/experiment/benchmark`: `{split,limit,model_ids,preset_ids,final_evaluation:false}` returns `{id,state,total}`. Persist IDs and config fingerprints before inference.
- `GET /api/experiment/job?id=`: `{id,state,done,total,error,summary}`. Summary has rows with model_id/preset_id/n/expected_n, lowercase metric fields, metric coverage, p50/p95, calls/tokens/cost, per_difficulty.
- `GET /api/experiment/runs`: `{runs:[{id,state,split,created_at,summary}]}`.
- `GET /api/experiment/export?id=&format=csv|json`: downloaded stored results.
- `POST /api/experiment/cancel`: `{id}`.

## Constraints

Python >=3.10, stdlib core/runtime remains runnable without torch. Training dependencies optional and isolated. Loopback HTTP and original Host/Origin/read-only guards remain. No unauthorised publishing, key logging, implicit GPT calls or fake model results. Data scripts may download only official pinned sources; preserve source usage terms. Ports, configs and results are local.

