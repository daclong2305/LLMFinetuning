# Execution asset readiness — 2026-11-03

Prepared private local assets for the pinned ViText2SQL syllable-level source. These are locally adapted execution metrics, not official leaderboard results.

| Split | Samples | EX / VES data eligible | EX coverage | TS eligible | TS coverage |
|---|---:|---:|---:|---:|---:|
| train | 6831 | 4739 | 69.4% | 582 | 8.5% |
| dev | 954 | 751 | 78.7% | 164 | 17.2% |
| test | 1908 | 1446 | 75.8% | 148 | 7.8% |

VES data eligibility does not guarantee timing completion for every query. The protocol requests 100 paired full executions with a 60-second budget per sample.

Imported 162/166 base databases and 987 published suite files. Audit validated 142 EX databases and 18 TS databases (607 distinct validated suite files).

Gold self-checks: 142 databases, all EX=1 and all completed 100 VES pairs. Invalid-SQL controls all received EX=0 and VES=0; available TS controls received TS=0. These checks verify evaluator/assets and do not measure a model.

Dev schemas with both EX and TS: `concert_singer`, `museum_visit`, `network_1`, `singer`, `voter_1`.

## Remaining unavailable assets

| Database | EX reason |
|---|---|
| academic | Duplicate target column names |
| bike_1 | Duplicate target column names |
| cre_Drama_Workshop_Groups | Duplicate target table names |
| culture_company | Gold SQL execution audit failed: near "sách": syntax error |
| customers_campaigns_ecommerce | Gold SQL execution audit failed: near ""khu nhà"": syntax error |
| department_management | Gold SQL execution audit failed: near "người": syntax error |
| department_store | Gold SQL execution audit failed: no such column: t1.id chuỗi cửa hàng bách hoá |
| document_management | Gold SQL execution audit failed: ORDER BY clause should come after INTERSECT not before |
| e_learning | Gold SQL execution audit failed: no such column: ngày |
| geo | Database has no data; synthetic empty schemas cannot qualify for EX |
| icfp_1 | Gold SQL execution audit failed: near "lượng": syntax error |
| imdb | Database has no data; synthetic empty schemas cannot qualify for EX |
| inn_1 | Gold SQL execution audit failed: no such column: t1.trẻ_em |
| movie_1 | Gold SQL execution audit failed: near "bình": syntax error |
| music_2 | Database has no data; synthetic empty schemas cannot qualify for EX |
| party_people | Gold SQL execution audit failed: near "thúc": syntax error |
| pilot_record | Gold SQL execution audit failed: no such column: tên |
| restaurants | Database has no data; synthetic empty schemas cannot qualify for EX |
| scholar | Database has no data; synthetic empty schemas cannot qualify for EX |
| ship_1 | Gold SQL execution audit failed: no such column: loại |
| storm_record | Gold SQL execution audit failed: near ""khu vực"": syntax error |
| student_transcripts_tracking | Gold SQL execution audit failed: near "bang": syntax error |
| wta_1 | Gold SQL execution audit failed: Could not decode to UTF-8 column 'h���' with text 'Treyes Albarrac��N' |
| yelp | Duplicate target column names |

Most remaining TS gaps are schemas without a published suite. Incompatible or incomplete suites are excluded in full. No generated rows, inferred cell translations or gold repairs were used.

## Local artifacts

- Full import provenance and mappings: `.runtime/datasets/vitext2sql/execution-assets-import.json`.
- Per-database readiness, coverage and self-check results: `.runtime/datasets/vitext2sql/execution-assets-readiness.json`.
- Evaluator assets: `execution-audit.json`, `test-suite-manifest.json`, `evaluation-options.json` in that same directory.
- Preserved architecture demo: `.runtime/datasets/vitext2sql/demo-backups/`.
- Download checksums/provenance: `.runtime/metric-sources/*.source.json`.

Dataset fingerprint: `69605a204c288e1673685571413b5a9e5d23df2928787a5098142ed34ebc066d`.

Validation: `python -m unittest discover -s tests -v` — 160 tests passed. Source ZIP hashes were verified. Existing saved runs were preserved; start a new run against the new snapshot.

Instructions: [execution-metrics.vi.md](../docs/execution-metrics.vi.md).

## Live local-model checks

The reloaded server confirms execution assets available, 142 validated base databases, a test-suite manifest and 100 VES repetitions.

- `qwen_base`, C0, `dev:00121` / `concert_singer`: status `ok`, EX=1, TS=1 over 32 states, VES=1.0145743403663823 with all 100 pairs completed. One local model call, no API charge. No metric was unavailable. Compact result: [execution-assets-live-check.json](execution-assets-live-check.json).
- The initial first-sample CLI pilot (`624ac104c61040aaa12d7837c9a6f064`, architecture) also completed: EX=0, VES=0 and TS unavailable because that schema has no published suite. Structural EM=1 does not imply matching literal values or execution results. Summary export: [execution-assets-pilot.csv](execution-assets-pilot.csv).

These single-sample checks verify the end-to-end flow; they do not establish model quality or comparative performance. Existing historical run files were not edited. Full source-bearing comparison data stays private in `.runtime/checks/execution-assets-live-check.json`.
