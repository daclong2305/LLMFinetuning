# Qwen fine-tuning workflow

The experiment compares the unmodified local `qwen2.5-coder:3b` against a separate ViText2SQL supervised fine-tune. Exporting data does **not** create a trained model. Until optimizer steps, saved weights, a merge and verified Ollama registration exist, the fine-tuned choice stays unavailable.

Run from the repository root with Python 3.10 or newer:

```powershell
python scripts/train_qwen.py --diagnostics
python scripts/train_qwen.py --prepare-only
python scripts/train_qwen.py --status
```

The exporter consumes `DatasetStore`'s pinned official train and dev splits. It verifies that their databases do not overlap and never requests test samples. `train.jsonl` and `dev.jsonl` store prompt messages separately from the target JSON SQL completion. The target SQL is absent from the prompt. Targets quote known identifiers using the evaluator's `executable_sql` policy, then compile against empty SQLite schemas. Invalid targets are excluded with IDs and reasons; immutable source labels remain untouched. This schema check uses no data and is not execution accuracy. The manifest records the raw dataset fingerprint, export hashes, original and retained sample counts, exclusions, normalization policy and explicit split roles. Dev is used for validation only.

The real preparation run on the pinned source retained **6,458 of 6,831 train rows** and **941 of 954 dev rows**. It excluded 373 train and 13 dev targets that failed schema compilation after identifier quoting. Training has not run: optional torch, transformers, peft, accelerate and bitsandbytes packages were absent in the inspected environment.

For a small pilot, use a separate output directory and `--limit 20`. A limit is recorded in provenance and does not constitute full dataset training.

The manifest's `data_snapshot_sha256` ties the source revision/fingerprint, roles, completion policy, counts/exclusions and export file hashes into one snapshot. Training verifies metadata and file hashes before encoding, before saving completed weights and during later trained-artifact validation. A repeated preparation in the same directory records prior snapshots; changing the dataset fingerprint or subset requires a new output directory. Active training holds a `.training.lock` and blocks preparation. If a process crashes, inspect the recorded PID before removing its stale lock.

## Isolated dependencies and GPU

Use a separate environment. The web server requires none of these packages:

```powershell
python -m venv .venv-training
.venv-training\Scripts\python.exe -m pip install --upgrade pip
```

Install the CUDA-compatible PyTorch wheel appropriate to your installed GPU driver following [PyTorch's installer](https://pytorch.org/get-started/locally/), then install the pinned optional dependencies:

```powershell
.venv-training\Scripts\python.exe -m pip install -r requirements-training.txt
.venv-training\Scripts\python.exe scripts/train_qwen.py --diagnostics
```

The known machine has a 6 GB RTX 3060 Laptop GPU and driver 546.30. Check CUDA availability in this environment before downloading weights. This workflow does not modify drivers. QLoRA uses NF4 4-bit weights, double quantization, fp16 compute, rank-8 adapters on attention projections, gradient checkpointing, batch size 1 and gradient accumulation 8. Sequence length defaults to 1024. This is a starting configuration; VRAM feasibility has not been verified on this machine. Long examples are excluded with IDs recorded rather than truncating away the supervised target. Prompt labels are -100; only the completion and EOS contribute to loss.

## Train and merge

Training explicitly downloads the official `Qwen/Qwen2.5-Coder-3B-Instruct` checkpoint. Obtain and record its 40-character repository commit SHA from the [official model repository](https://huggingface.co/Qwen/Qwen2.5-Coder-3B-Instruct/tree/main). Review its Qwen Research license before use. Supply the SHA instead of a moving branch:

```powershell
.venv-training\Scripts\python.exe scripts/train_qwen.py --train --base-revision <MODEL_COMMIT_SHA>
.venv-training\Scripts\python.exe scripts/train_qwen.py --merge
```

`--max-steps 10` supports a smoke training run, and the cap is recorded. `--quantization lora` uses fp16 base weights and generally requires more VRAM. Seed 42 is recorded alongside package versions, hardware, excluded examples, hyperparameters, loss metrics and optimizer steps. GPU kernels can still differ across hardware and package environments.

After training, `adapter/` contains PEFT adapter weights only. `training_manifest.json` says `artifact_kind: adapter`; it is not an independently runnable full model. Merging reloads the exact pinned base model on CPU in fp32, applies the adapter, and writes `merged/`. Expect substantial system RAM and disk use. The manifest then says `artifact_kind: merged`, hashes every saved file, and retains adapter hashes. The merge must complete before Ollama registration.

## Import into Ollama

With Ollama running:

```powershell
.venv-training\Scripts\python.exe scripts/train_qwen.py --register-ollama
# Optional explicit executable path:
.venv-training\Scripts\python.exe scripts/train_qwen.py --register-ollama --ollama-executable F:\Tools\ollama.exe
```

This explicit action writes a Modelfile pointing to merged Safetensors and invokes `ollama create qwen2.5-coder-vitext2sql:3b --quantize q4_K_M`. It verifies the installed model's digest, refuses a digest equal to the installed base model, and records the exact artifact hashes associated with that digest. Model import support depends on the installed Ollama version; a failure leaves the choice unavailable. No model is pushed or published. See [Ollama's import documentation](https://docs.ollama.com/import).

Executable resolution prefers `--ollama-executable`, then the repository's `.runtime/ollama/ollama.exe`, then PATH. An invalid explicit path produces a diagnostic instead of selecting a different executable. No system installation is attempted. Registry metadata includes the installed Ollama model digest and quantization level for reproducibility snapshots.

The registry config entry uses `trained: true`, the same Ollama model name and `training_manifest: .runtime/training/qwen-vitext2sql/training_manifest.json`. Availability requires successful training, train-only provenance, intact saved weights, a merged artifact and the currently installed digest matching registration. Copying or renaming the base model cannot satisfy this workflow. Manifests are local reproducibility records, not signed attestations against a malicious local editor.

## Provider extension

`BackendRegistry(config).create(model_id).generate(messages)` returns text, input/output/cached tokens, configured USD API cost, model and response ID. Unknown usage stays null. `BackendError.usage` retains metering on failed or incomplete responses. OpenAI uses Responses JSON output with `store:false`; local Ollama API cost is zero and excludes training, electricity and hardware costs. Cached OpenAI input is charged at the configured cached rate rather than ordinary input rate. Registry metadata and provider errors never return credentials.

For an extra provider, call `registry.register_provider(name, factory, availability)` before use. The factory accepts the model config and returns an object implementing `generate(messages)` with the same response/error contract. The availability callable returns `(ready, reason)` and must not include credentials in its reason. The common pipeline then uses the configured model ID without provider-specific branches.

Reference implementation guidance: [Qwen model card and chat template](https://huggingface.co/Qwen/Qwen2.5-Coder-3B-Instruct), [PEFT quantization guide](https://huggingface.co/docs/peft/main/en/developer_guides/quantization), and [Transformers PEFT integration](https://huggingface.co/docs/transformers/main/en/peft).
