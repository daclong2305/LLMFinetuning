"""Explicit prepare/train/merge/import CLI. Running diagnostics never downloads weights."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from text2sql_demo.experiment.training import (BASE_MODEL, dependency_diagnostics, prepare_training_data,
                                               train_qwen, merge_adapter, export_gguf, register_ollama, training_status)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    for action in ('prepare-only', 'train', 'merge', 'export-gguf', 'register-ollama', 'diagnostics', 'status'):
        actions.add_argument('--' + action, action='store_true')
    parser.add_argument('--dataset-dir', default='.runtime/datasets/vitext2sql')
    parser.add_argument('--output-dir', default='.runtime/training/qwen-vitext2sql')
    parser.add_argument('--base-model', default=BASE_MODEL)
    parser.add_argument('--base-revision', help='Pinned Hugging Face commit SHA; required for training')
    parser.add_argument('--quantization', choices=['qlora', 'lora'], default='qlora')
    parser.add_argument('--epochs', type=float, default=1)
    parser.add_argument('--max-length', type=int, default=1024)
    parser.add_argument('--max-steps', type=int, default=-1)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--limit', type=int, help='Explicit train/dev preparation subset for a pilot')
    parser.add_argument('--ollama-model', default='qwen2.5-coder-vitext2sql:3b')
    parser.add_argument('--ollama-url', default='http://127.0.0.1:11434')
    parser.add_argument('--ollama-executable', help='Explicit path to Ollama; default prefers the project portable runtime, then PATH')
    parser.add_argument('--ollama-quantization', choices=['int4', 'int8', 'nvfp4', 'mxfp4', 'mxfp8', 'q4_K_M'], default='int4',
                        help='Safetensors import type; int4 for current Ollama, q4_K_M only for older compatible importers')
    parser.add_argument('--ollama-models-dir', help='Model store used by the running Ollama server; portable default is .runtime/models')
    parser.add_argument('--gguf-converter', help='Path to llama.cpp convert_hf_to_gguf.py; default .runtime/tools/llama.cpp-b4514')
    parser.add_argument('--gguf-quantizer', help='Path to llama-quantize; default portable Ollama bundled executable')
    args = parser.parse_args(argv)
    try:
        if args.diagnostics: result = dependency_diagnostics(args.quantization)
        elif args.status: result = training_status(Path(args.output_dir) / 'training_manifest.json')
        elif args.prepare_only:
            from text2sql_demo.experiment.dataset import DatasetStore
            result = prepare_training_data(DatasetStore(args.dataset_dir), args.output_dir, limit=args.limit)
        elif args.train:
            result = train_qwen(args.output_dir, args.base_model, args.base_revision, args.quantization,
                                args.epochs, args.max_length, args.seed, max_steps=args.max_steps)
        elif args.merge: result = merge_adapter(args.output_dir)
        elif args.export_gguf: result = export_gguf(args.output_dir, args.gguf_converter, args.gguf_quantizer)
        else: result = register_ollama(args.output_dir, args.ollama_model, args.ollama_url, args.ollama_executable,
                                      quantization=args.ollama_quantization, models_dir=args.ollama_models_dir)
        # Escaped JSON is portable across legacy Windows console encodings.
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__': raise SystemExit(main())
