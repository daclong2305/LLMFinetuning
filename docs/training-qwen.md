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

For Qwen2 on Ollama 0.35.1, direct Safetensors import takes the MLX path and rejects `Qwen2ForCausalLM`.
Export the already merged checkpoint to GGUF instead; no training or merge is repeated:

```powershell
git clone --depth 1 --branch b4514 https://github.com/ggml-org/llama.cpp .runtime/tools/llama.cpp-b4514
.venv-training\Scripts\python.exe -m pip install -r requirements-gguf.txt
.venv-training\Scripts\python.exe scripts/train_qwen.py --export-gguf --output-dir .runtime/training/qwen-kaggle-merged/qwen-kaggle
.venv-training\Scripts\python.exe scripts/train_qwen.py --register-ollama --output-dir .runtime/training/qwen-kaggle-merged/qwen-kaggle --ollama-models-dir .runtime/models
```

The pinned converter tag resolves to `ec7f3ac9ab33e46b136eb5ab6a76c4d81f57c7f1`. Conversion reads tensors lazily on CPU, uses a disk-backed temporary file and writes an F16 intermediate. The bundled `llama-quantize` then produces `Q4_K_M` with two threads and a 128 MiB tensor-row buffer. This lowers peak memory compared with loading and merging a full FP32 model; it is not a guarantee against system faults. Keep enough RAM and disk available. The intermediate is removed only after successful export.

Export records the GGUF hash, source merged-weight hashes, converter and quantizer hashes, precision and settings in `gguf_export`. Registration verifies those records and imports the GGUF without passing `--quantize`, bypassing MLX. A changed GGUF or changed source weights invalidates availability. A repeat successful export verifies and reuses the recorded file. Safetensors and adapters are retained. The default quantizer is `.runtime/ollama/lib/ollama/llama-quantize.exe`; for Kaggle/Linux, supply the appropriate converter and quantizer through `--gguf-converter` and `--gguf-quantizer`.

An exclusive `.gguf-export.lock` prevents overlapping conversions; inspect the recorded PID before removing a stale lock. Completed conversion is recorded in pending metadata before final publication, so retrying a failed manifest commit verifies and reuses the completed GGUF rather than converting again. Registration compares the CLI-created model manifest's SHA256 with the server's installed model digest, and checks that its model layer is the exported GGUF hash. A same-name model in a different server store cannot satisfy registration.

With Ollama running:

```powershell
.venv-training\Scripts\python.exe scripts/train_qwen.py --register-ollama
# Optional explicit executable path:
.venv-training\Scripts\python.exe scripts/train_qwen.py --register-ollama --ollama-executable F:\Tools\ollama.exe
```

This explicit action writes a Modelfile pointing to merged Safetensors and invokes `ollama create qwen2.5-coder-vitext2sql:3b --quantize int4`. Current Ollama Safetensors import accepts `int4`, `int8`, `nvfp4`, `mxfp4` and `mxfp8`; select a type with `--ollama-quantization`. The legacy `q4_K_M` option is only for older compatible importers and is not equivalent to native `int4`. It verifies the installed model's digest, refuses a digest equal to the installed base model, and records the exact artifact hashes associated with that digest and the requested quantization. Model import support depends on the installed Ollama version; a failure leaves the choice unavailable. No model is pushed or published. See [Ollama's import documentation](https://docs.ollama.com/import).

Executable resolution prefers `--ollama-executable`, then the repository's `.runtime/ollama/ollama.exe`, then PATH. An invalid explicit path produces a diagnostic instead of selecting a different executable. No system installation is attempted. Registry metadata includes the installed Ollama model digest and quantization level for reproducibility snapshots.

Safetensors creation in current Ollama writes to the CLI's local model store. `--ollama-models-dir` must match the running server's `OLLAMA_MODELS`; otherwise the server may not see a successfully created model. The portable executable defaults to the project's `.runtime/models` when `OLLAMA_MODELS` is unset. CLI create failures return a concise diagnostic and do not update registration metadata.

The registry config entry uses `trained: true`, the same Ollama model name and the manifest path for the actual run. On this machine it is `.runtime/training/qwen-kaggle-merged/qwen-kaggle/training_manifest.json`; a default local training run uses `.runtime/training/qwen-vitext2sql/training_manifest.json`. Availability requires successful training, train-only provenance, intact saved weights, a merged artifact and the currently installed digest matching registration. Copying or renaming the base model cannot satisfy this workflow. Manifests are local reproducibility records, not signed attestations against a malicious local editor.

## Provider extension

`BackendRegistry(config).create(model_id).generate(messages)` returns text, input/output/cached tokens, configured USD API cost, model and response ID. Unknown usage stays null. `BackendError.usage` retains metering on failed or incomplete responses. OpenAI uses Responses JSON output with `store:false`; local Ollama API cost is zero and excludes training, electricity and hardware costs. Cached OpenAI input is charged at the configured cached rate rather than ordinary input rate. Registry metadata and provider errors never return credentials.

For an extra provider, call `registry.register_provider(name, factory, availability)` before use. The factory accepts the model config and returns an object implementing `generate(messages)` with the same response/error contract. The availability callable returns `(ready, reason)` and must not include credentials in its reason. The common pipeline then uses the configured model ID without provider-specific branches.

Reference implementation guidance: [Qwen model card and chat template](https://huggingface.co/Qwen/Qwen2.5-Coder-3B-Instruct), [PEFT quantization guide](https://huggingface.co/docs/peft/main/en/developer_guides/quantization), and [Transformers PEFT integration](https://huggingface.co/docs/transformers/main/en/peft).
