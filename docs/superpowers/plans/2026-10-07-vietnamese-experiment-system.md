# Vietnamese Text-to-SQL Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Upgrade the demo into an extensible Vietnamese Text-to-SQL experiment system with honest comparative metrics.

**Architecture:** Dataset, evaluator, backend and shared C0-C4 pipeline are independently testable modules. A background benchmark service persists exact datasets/configs and exposes real results to a Vietnamese dashboard.

**Tech Stack:** Python 3.10 stdlib, SQLite, vanilla JavaScript/CSS; optional Transformers/PEFT for training; attributed official Spider evaluator.

**Spec:** ../specs/2026-10-07-vietnamese-experiment-system.md

## Global Constraints

- Core runnable without training dependencies; preserve retail demo at /legacy.
- No fake trained model, simulated benchmark, leaked target gold or test retrieval.
- Unknown/unavailable metrics null with reasons; count model failures and expose coverage.
- Fixed data revision and GPT snapshot; all-stage tokens/calls/cost.
- Work in place: no Git repository or worktree exists.

## Review Focus

- Unicode table/column names, spaces and aliases must be parsed without conflating different columns.
- Wrong SQL with an identical 200-row preview must fail full-result evaluation.
- Errors after one successful auxiliary model call must still retain usage and cost.
- Cancelled/partial benchmarks must not look like full completed test runs.
- Missing SQLite/key/checkpoint must be unavailable rather than silently selecting another backend or scoring on an empty database.

### Task 1: Official dataset and evaluation

**Files:** experiment/dataset.py, experiment/evaluation.py, vendor/spider/*, scripts/prepare_vitext2sql.py, tests/test_experiment_data.py, tests/test_experiment_metrics.py.

**Interfaces:** DatasetStore/evaluate_prediction exactly as spec.

- [x] Write failing tests: split leakage rejection, Unicode schema, EM/CM disagreement, full rows/order/duplicates, missing data null EX.
- [x] Run targeted unittest and confirm missing feature failures.
- [x] Implement pinned acquisition, source lock and dataset loading; attributed evaluator adapter and execution audit.
- [x] Run targeted tests, then baseline suite; record real dataset inspection.

### Task 2: Model adapters and training

**Files:** experiment/backends.py, experiment/training.py, scripts/train_qwen.py, requirements-training.txt, tests/test_experiment_backends.py, tests/test_training.py.

**Interfaces:** BackendRegistry and normalized generate response as spec.

- [x] Write/run failing tests for HTTP payload/usage, cached price, hidden credentials, FT provenance, train-only prompt completion labels and missing dependency diagnostics.
- [x] Implement registry, Ollama/OpenAI Responses adapters, configuration-driven settings and env loading.
- [x] Implement SFT data export, QLoRA/LoRA training CLI, manifest creation and Ollama import instructions.
- [x] Run targeted and whole tests; do not claim training when only exports ran.

### Task 3: Dashboard

**Files:** demo/static/experiment.html, experiment.js, experiment.css.

**Interfaces:** HTTP contract from spec; missing metrics use reasons and state badges.

- [x] Build accessible Vietnamese comparison and benchmark UI with model choices, C1-C4 switches, presets, trace/schema/gold inspection, progress/cancel and CSV/JSON export.
- [x] Show before/after Qwen only when separate artifacts exist; do not populate numeric placeholder results.
- [x] Verify browser behavior, request errors, empty and unavailable state; root later wires routes.

### Task 4: Shared pipeline and benchmark service

**Files:** experiment/pipeline.py, benchmark.py, service.py, config/experiment.json, tests/test_experiment_pipeline.py, tests/test_benchmark.py, tests/test_experiment_server.py; modify server.py.

**Interfaces:** Run/API contract from spec consumes Tasks 1-2.

- [x] Write/run failing tests for C0/C1-C4 stages, leakage, calls/usage on errors, bounded repair, benchmark denominators and cancellation.
- [x] Implement generic prompt/retrieval/linking and staged execution. Add persisted benchmark aggregation and runs/export APIs.
- [x] Wire loopback guarded routes and preserve legacy HTTP/tests.
- [x] Run whole unittest suite and real HTTP smoke on a separate port.

### Task 5: Documentation, integration and review

**Files:** README.md, reports/experiment-verification.md, scripts/run_benchmark.py, .env.example, .gitignore.

- [x] Document setup, official dataset caveats, metrics, training/registration, fixed models, extension, reproducibility and API key handling.
- [x] Download/audit real ViText2SQL; verify gold/schema compatibility and training export counts.
- [x] Run full tests, browser smoke, real Qwen pilot and benchmark when resources permit; label all unavailable prerequisites.
- [x] Fresh independent review; reproduce/fix important findings with failing tests and a final full suite.

