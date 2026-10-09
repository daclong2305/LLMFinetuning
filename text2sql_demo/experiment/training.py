"""Optional, reproducible completion-only Qwen SFT and provenance validation."""
import hashlib
import contextlib
import importlib.metadata
import importlib.util
import json
import os
import random
import re
import sqlite3
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


BASE_MODEL = 'Qwen/Qwen2.5-Coder-3B-Instruct'


def _snapshot_fingerprint(manifest):
    keys = ('dataset_fingerprint', 'dataset_revision', 'trained_splits', 'validation_split', 'counts',
            'original_counts', 'excluded_samples', 'completion_policy', 'data_files', 'training_limit', 'test_used')
    snapshot = {key: manifest.get(key) for key in keys}
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def _write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): digest.update(block)
    return digest.hexdigest()


def dependency_diagnostics(quantization='qlora'):
    packages = ['torch', 'transformers', 'peft', 'accelerate']
    if quantization == 'qlora': packages.append('bitsandbytes')
    missing, versions = [], {}
    for package in packages:
        if importlib.util.find_spec(package) is None: missing.append(package)
        else:
            try: versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError: versions[package] = 'unknown'
    return {'ready': not missing, 'missing': missing, 'versions': versions, 'python': sys.version.split()[0],
            'install_hint': 'Use an isolated virtual environment and requirements-training.txt. Install a CUDA-compatible PyTorch build separately.'}


def prepare_training_data(store, output_dir, limit=None):
    summary = store.summary()
    if not summary.get('ready'): raise ValueError('Dataset is not ready.')
    if not summary.get('fingerprint'): raise ValueError('Dataset fingerprint is required.')
    rows = {split: list(store.samples(split, limit=limit)) for split in ('train', 'dev')}
    if not rows['train'] or not rows['dev']: raise ValueError('Training and validation data must be nonempty.')
    for split, samples in rows.items():
        if any(sample.get('split') != split for sample in samples): raise ValueError('Sample split disagrees with requested split.')
    if {row['db_id'] for row in rows['train']} & {row['db_id'] for row in rows['dev']}:
        raise ValueError('Train/dev database overlap is forbidden.')
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    existing = out / 'training_manifest.json'
    previous = json.loads(existing.read_text(encoding='utf-8')) if existing.exists() else None
    if (out / '.training.lock').exists() or (previous and previous.get('status') in ('training', 'trained')):
        raise ValueError('Do not overwrite an active or trained run; use another output directory.')
    if previous and (previous.get('dataset_fingerprint') != summary['fingerprint'] or previous.get('training_limit') != limit):
        raise ValueError('Prepared dataset snapshot changed; use another output directory.')
    from .evaluation import executable_sql
    files, excluded, counts = {}, {'train': [], 'dev': []}, {'train': 0, 'dev': 0}
    for split, samples in rows.items():
        path = out / (split + '.jsonl')
        with path.open('w', encoding='utf-8', newline='\n') as stream:
            for sample in samples:
                schema = store.schema(sample['db_id'])
                schema_text = '\n'.join(value.get('ddl', '') for value in schema.values())
                normalized_sql = executable_sql(sample['gold_sql'], schema)
                try:
                    if not re.match(r'^\s*(SELECT|WITH)\b', normalized_sql, re.I): raise ValueError('Target must be read-only SELECT/WITH SQL.')
                    # Compilation only, on empty schemas; this never constitutes EX accuracy.
                    con = sqlite3.connect(':memory:')
                    try:
                        con.executescript(schema_text)
                        con.execute('PRAGMA query_only=ON')
                        con.execute('EXPLAIN QUERY PLAN ' + normalized_sql).fetchall()
                    finally: con.close()
                except (sqlite3.Error, ValueError) as exc:
                    excluded[split].append({'id': sample['id'], 'db_id': sample['db_id'], 'reason': str(exc)})
                    continue
                record = {'id': sample['id'], 'db_id': sample['db_id'], 'split': split,
                          'messages': [{'role': 'system', 'content': 'Chuyển câu hỏi tiếng Việt thành SQLite SQL. Chỉ trả JSON với trường sql. Dùng đúng schema được cung cấp.'},
                                       {'role': 'user', 'content': 'Schema:\n' + schema_text + '\nCâu hỏi: ' + sample['question']}],
                          'completion': json.dumps({'sql': normalized_sql}, ensure_ascii=False)}
                stream.write(json.dumps(record, ensure_ascii=False) + '\n')
                counts[split] += 1
        files[path.name] = file_sha256(path)
    if not all(counts.values()): raise ValueError('No schema-valid targets remain in a required split.')
    manifest = {'format_version': 1, 'status': 'prepared', 'trained_steps': 0, 'artifact_kind': None,
                'created_at': datetime.now(timezone.utc).isoformat(), 'dataset_fingerprint': summary['fingerprint'],
                'dataset_revision': summary.get('revision'), 'trained_splits': ['train'], 'validation_split': 'dev',
                'counts': counts, 'original_counts': {split: len(samples) for split, samples in rows.items()},
                'excluded_samples': excluded, 'completion_policy': 'quote known identifiers with evaluation.executable_sql; exclude targets failing schema-only SQLite compilation; preserve original source labels',
                'data_files': files,
                'training_limit': limit, 'test_used': False}
    manifest['data_snapshot_sha256'] = _snapshot_fingerprint(manifest)
    if previous:
        manifest['preparation_history'] = previous.get('preparation_history', []) + [
            {'created_at': previous.get('created_at'), 'data_snapshot_sha256': previous.get('data_snapshot_sha256', _snapshot_fingerprint(previous)),
             'data_files': previous.get('data_files'), 'counts': previous.get('counts')}]
    _write_json(existing, manifest)
    return manifest


def encode_completion(record, tokenizer, max_length=1024):
    prompt_ids = tokenizer.apply_chat_template(record['messages'], tokenize=True, add_generation_prompt=True)
    target_ids = tokenizer.encode(record['completion'], add_special_tokens=False)
    if tokenizer.eos_token_id is None: raise ValueError('Tokenizer requires an EOS token.')
    target_ids = target_ids + [tokenizer.eos_token_id]
    input_ids = list(prompt_ids) + target_ids
    if len(input_ids) > max_length: raise ValueError('Example exceeds maximum sequence length; use a larger length or explicitly exclude it.')
    return {'input_ids': input_ids, 'attention_mask': [1] * len(input_ids), 'labels': [-100] * len(prompt_ids) + target_ids}


def _verified_gguf_export(root, manifest):
    export = manifest.get('gguf_export')
    if not isinstance(export, dict) or export.get('source_artifact_files') != manifest.get('artifact_files'):
        raise ValueError('GGUF export is not tied to these merged weights.')
    name = export.get('path')
    if not isinstance(name, str) or not name or export.get('quantization') != 'Q4_K_M':
        raise ValueError('Invalid GGUF export metadata.')
    artifact = (root / name).resolve()
    if not artifact.is_relative_to(root) or artifact.suffix != '.gguf' or not artifact.is_file():
        raise ValueError('GGUF export is missing or outside the run directory.')
    with artifact.open('rb') as stream:
        if stream.read(4) != b'GGUF': raise ValueError('Invalid GGUF export file.')
    if file_sha256(artifact) != export.get('sha256'): raise ValueError('GGUF export hash mismatch.')
    return artifact, export


def validate_training_manifest(path, model=None):
    path = Path(path)
    if not path.is_file(): raise ValueError('A trained manifest is required.')
    try: manifest = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError): raise ValueError('Invalid trained manifest.') from None
    if manifest.get('status') != 'trained' or not isinstance(manifest.get('trained_steps'), int) or manifest['trained_steps'] <= 0:
        raise ValueError('Manifest is not a successfully trained run.')
    if manifest.get('trained_splits') != ['train'] or manifest.get('validation_split') != 'dev' or manifest.get('test_used'):
        raise ValueError('Training provenance includes forbidden splits.')
    if not all(manifest.get(key) for key in ('base_model', 'base_revision', 'dataset_fingerprint')):
        raise ValueError('Missing trained provenance.')
    if manifest.get('artifact_kind') not in ('adapter', 'merged'): raise ValueError('Unknown trained artifact kind.')
    files = manifest.get('artifact_files')
    if not isinstance(files, dict) or not files or not any(name.endswith('.safetensors') for name in files):
        raise ValueError('Trained weight artifact files are required.')
    root = path.parent.resolve()
    if manifest.get('data_files') is not None:
        _verified_data(root)
    for name, expected in files.items():
        artifact = (root / name).resolve()
        if not artifact.is_relative_to(root) or not artifact.is_file(): raise ValueError('Trained artifact is missing or outside run directory.')
        if file_sha256(artifact) != expected: raise ValueError('Trained artifact hash mismatch.')
    if manifest.get('gguf_export') is not None:
        _verified_gguf_export(root, manifest)
    if model is not None:
        registration = manifest.get('registration') or {}
        if (manifest['artifact_kind'] != 'merged' or registration.get('model') != model or not registration.get('digest')
                or registration.get('artifact_files') != files):
            raise ValueError('Merged trained artifact must be explicitly registered for this model.')
        if manifest.get('gguf_export') is not None:
            export = manifest['gguf_export']
            if registration.get('import_artifact') != {'path': export['path'], 'sha256': export['sha256']}:
                raise ValueError('Registered model does not match the GGUF export.')
    return manifest


def training_status(path):
    result = {'state': 'unavailable', 'ready': False, 'reason': 'No trained artifact is available.', 'dependencies': dependency_diagnostics()}
    try:
        manifest = validate_training_manifest(path)
        result.update(state='trained', ready=True, reason=None, artifact_kind=manifest['artifact_kind'],
                      trained_steps=manifest['trained_steps'], dataset_fingerprint=manifest['dataset_fingerprint'],
                      registration=manifest.get('registration'))
    except (OSError, ValueError, TypeError):
        try:
            manifest = json.loads(Path(path).read_text(encoding='utf-8'))
            if manifest.get('status') == 'prepared': result.update(state='prepared', reason='Data prepared; no training has completed.', counts=manifest.get('counts'))
        except (OSError, ValueError, TypeError): pass
    return result


def _verified_data(out):
    manifest = json.loads((out / 'training_manifest.json').read_text(encoding='utf-8'))
    if manifest.get('trained_splits') != ['train'] or manifest.get('validation_split') != 'dev' or manifest.get('test_used'):
        raise ValueError('Invalid data provenance.')
    if manifest.get('data_snapshot_sha256') != _snapshot_fingerprint(manifest):
        raise ValueError('Prepared data snapshot provenance mismatch; prepare a verified export first.')
    for name in ('train.jsonl', 'dev.jsonl'):
        if file_sha256(out / name) != manifest.get('data_files', {}).get(name): raise ValueError('Prepared data hash mismatch.')
    return manifest


def _train_qwen_impl(output_dir, base_model=BASE_MODEL, base_revision=None, quantization='qlora', epochs=1,
               max_length=1024, seed=42, learning_rate=2e-4, gradient_accumulation_steps=8, max_steps=-1):
    """Downloads weights only when this explicitly requested function is invoked."""
    diagnostics = dependency_diagnostics(quantization)
    if not diagnostics['ready']: raise RuntimeError('Missing training dependencies: ' + ', '.join(diagnostics['missing']))
    if not base_revision or len(base_revision) != 40 or any(ch not in '0123456789abcdef' for ch in base_revision.lower()):
        raise ValueError('Training requires a pinned 40-character Hugging Face model commit revision.')
    if quantization not in ('qlora', 'lora'): raise ValueError('Choose qlora or lora.')
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, Trainer, TrainingArguments, set_seed
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    if not torch.cuda.is_available(): raise RuntimeError('CUDA GPU is required for this training workflow.')
    out = Path(output_dir); manifest = _verified_data(out)
    if manifest.get('status') == 'trained': raise ValueError('Run already trained; use another output directory.')
    set_seed(seed); random.seed(seed)
    tokenizer = AutoTokenizer.from_pretrained(base_model, revision=base_revision)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = 'right'
    encoded, excluded = {}, {}
    for split in ('train', 'dev'):
        encoded[split], excluded[split] = [], []
        for line in (out / (split + '.jsonl')).read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            if row.get('split') != split: raise ValueError('Prepared row split mismatch.')
            try: encoded[split].append(encode_completion(row, tokenizer, max_length))
            except ValueError as exc:
                if 'length' not in str(exc): raise
                excluded[split].append(row['id'])
        if not encoded[split]: raise ValueError('No examples fit max_length in ' + split)
    if _verified_data(out)['data_snapshot_sha256'] != manifest['data_snapshot_sha256']:
        raise ValueError('Prepared data snapshot changed during encoding.')
    kwargs = {'revision': base_revision, 'torch_dtype': torch.float16, 'device_map': {'': 0}}
    if quantization == 'qlora':
        kwargs['quantization_config'] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                                                        bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.float16)
    model = AutoModelForCausalLM.from_pretrained(base_model, **kwargs)
    model.config.use_cache = False
    if quantization == 'qlora': model = prepare_model_for_kbit_training(model)
    else:
        model.gradient_checkpointing_enable(); model.enable_input_require_grads()
    lora = LoraConfig(r=8, lora_alpha=16, lora_dropout=.05, bias='none', task_type='CAUSAL_LM',
                      target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj'])
    model = get_peft_model(model, lora)
    def collate(features):
        length = max(len(feature['input_ids']) for feature in features)
        batch = {}
        for name, pad in [('input_ids', tokenizer.pad_token_id), ('attention_mask', 0), ('labels', -100)]:
            batch[name] = torch.tensor([feature[name] + [pad] * (length - len(feature[name])) for feature in features], dtype=torch.long)
        return batch
    args = TrainingArguments(output_dir=str(out / 'checkpoints'), num_train_epochs=epochs, max_steps=max_steps,
                             per_device_train_batch_size=1, per_device_eval_batch_size=1,
                             gradient_accumulation_steps=gradient_accumulation_steps, learning_rate=learning_rate,
                             fp16=True, gradient_checkpointing=True, eval_strategy='epoch', save_strategy='epoch',
                             logging_steps=10, report_to=[], seed=seed, data_seed=seed, optim='adamw_torch',
                             save_total_limit=2, remove_unused_columns=False)
    trainer = Trainer(model=model, args=args, train_dataset=encoded['train'], eval_dataset=encoded['dev'], data_collator=collate)
    result = trainer.train()
    if trainer.state.global_step <= 0: raise RuntimeError('No optimizer steps completed.')
    if _verified_data(out)['data_snapshot_sha256'] != manifest['data_snapshot_sha256']:
        raise ValueError('Prepared data snapshot changed during training.')
    adapter_dir = out / 'adapter'; model.save_pretrained(adapter_dir, safe_serialization=True); tokenizer.save_pretrained(adapter_dir)
    files = {str(path.relative_to(out)).replace('\\', '/'): file_sha256(path) for path in adapter_dir.iterdir() if path.is_file()}
    manifest.update(status='trained', completed_at=datetime.now(timezone.utc).isoformat(), artifact_kind='adapter',
                    artifact_files=files, trained_steps=trainer.state.global_step, base_model=base_model, base_revision=base_revision,
                    seed=seed, packages=diagnostics['versions'], training_parameters={'quantization': quantization, 'epochs': epochs,
                    'max_length': max_length, 'learning_rate': learning_rate, 'gradient_accumulation_steps': gradient_accumulation_steps,
                    'max_steps': max_steps, 'lora': lora.to_dict()}, excluded_ids=excluded,
                    used_counts={split: len(value) for split, value in encoded.items()}, metrics=result.metrics,
                    hardware={'gpu': torch.cuda.get_device_name(0), 'cuda': torch.version.cuda, 'platform': sys.platform})
    # PEFT's serialized config may contain sets/Enums; use its saved JSON as the canonical representation.
    manifest['training_parameters']['lora'] = json.loads((adapter_dir / 'adapter_config.json').read_text(encoding='utf-8'))
    _write_json(out / 'training_manifest.json', manifest)
    return manifest


def train_qwen(output_dir, base_model=BASE_MODEL, base_revision=None, quantization='qlora', epochs=1,
               max_length=1024, seed=42, learning_rate=2e-4, gradient_accumulation_steps=8, max_steps=-1):
    diagnostics = dependency_diagnostics(quantization)
    if not diagnostics['ready']: raise RuntimeError('Missing training dependencies: ' + ', '.join(diagnostics['missing']))
    out = Path(output_dir)
    _verified_data(out)
    lock = out / '.training.lock'
    try:
        with lock.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps({'pid': os.getpid(), 'created_at': datetime.now(timezone.utc).isoformat()}))
    except FileExistsError: raise RuntimeError('Training run is already active; use another output directory.') from None
    try:
        return _train_qwen_impl(output_dir, base_model, base_revision, quantization, epochs, max_length, seed,
                                learning_rate, gradient_accumulation_steps, max_steps)
    finally: lock.unlink(missing_ok=True)


def merge_adapter(output_dir):
    out = Path(output_dir); manifest = validate_training_manifest(out / 'training_manifest.json')
    if manifest['artifact_kind'] != 'adapter': raise ValueError('Expected adapter artifact to merge.')
    diagnostics = dependency_diagnostics('lora')
    if not diagnostics['ready']: raise RuntimeError('Missing merge dependencies: ' + ', '.join(diagnostics['missing']))
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel
    # Merge on CPU in full precision; do not merge directly into quantized weights.
    base = AutoModelForCausalLM.from_pretrained(manifest['base_model'], revision=manifest['base_revision'], torch_dtype=torch.float32, device_map={'': 'cpu'})
    merged = PeftModel.from_pretrained(base, out / 'adapter').merge_and_unload()
    merged_dir = out / 'merged'; merged.save_pretrained(merged_dir, safe_serialization=True, max_shard_size='2GB')
    AutoTokenizer.from_pretrained(out / 'adapter').save_pretrained(merged_dir)
    manifest['adapter_files'] = manifest['artifact_files']
    manifest['artifact_files'] = {str(path.relative_to(out)).replace('\\', '/'): file_sha256(path) for path in merged_dir.iterdir() if path.is_file()}
    manifest['artifact_kind'] = 'merged'; manifest['merged_at'] = datetime.now(timezone.utc).isoformat()
    _write_json(out / 'training_manifest.json', manifest)
    return manifest


def export_gguf(output_dir, converter=None, quantizer=None):
    out = Path(output_dir).resolve()
    lock = out / '.gguf-export.lock'
    try:
        stream = lock.open('x', encoding='utf-8')
    except FileExistsError:
        raise RuntimeError('GGUF export is already active; inspect the recorded PID before removing a stale lock.') from None
    try:
        with stream:
            json.dump({'pid': os.getpid(), 'created_at': datetime.now(timezone.utc).isoformat()}, stream)
        return _export_gguf_impl(out, converter, quantizer)
    finally:
        lock.unlink(missing_ok=True)


def _finish_gguf_export(out, manifest, export, pending, intermediate, partial, target):
    candidate = target if target.exists() else partial
    candidate_export = {**export, 'path': candidate.relative_to(out).as_posix()}
    _verified_gguf_export(out, {**manifest, 'gguf_export': candidate_export})
    if candidate != target: candidate.replace(target)
    manifest['gguf_export'] = export
    manifest.pop('registration', None)
    _write_json(out / 'training_manifest.json', manifest)
    for temporary in (pending, intermediate):
        with contextlib.suppress(OSError): temporary.unlink(missing_ok=True)
    return export


def _export_gguf_impl(output_dir, converter=None, quantizer=None):
    """Convert already merged weights to F16 GGUF and bounded-buffer Q4_K_M; never train or merge."""
    out = Path(output_dir).resolve()
    manifest = validate_training_manifest(out / 'training_manifest.json')
    if manifest['artifact_kind'] != 'merged': raise ValueError('Merge the adapter before GGUF export.')
    if manifest.get('gguf_export') is not None:
        return manifest['gguf_export']
    gguf_dir = out / 'gguf'; gguf_dir.mkdir(exist_ok=True)
    if not gguf_dir.resolve().is_relative_to(out): raise ValueError('GGUF output directory is outside the run directory.')
    intermediate = gguf_dir / 'model-f16.tmp.gguf'
    partial = gguf_dir / 'model-q4_k_m.tmp.gguf'
    target = gguf_dir / 'model-q4_k_m.gguf'
    pending = gguf_dir / 'export-pending.json'
    if pending.is_file():
        export = json.loads(pending.read_text(encoding='utf-8'))
        if export.get('path') != target.relative_to(out).as_posix(): raise ValueError('Invalid pending GGUF export path.')
        return _finish_gguf_export(out, manifest, export, pending, intermediate, partial, target)
    project_root = Path(__file__).resolve().parents[2]
    converter = Path(converter) if converter else project_root / '.runtime/tools/llama.cpp-b4514/convert_hf_to_gguf.py'
    quantizer = Path(quantizer) if quantizer else project_root / '.runtime/ollama/lib/ollama/llama-quantize.exe'
    converter, quantizer = converter.resolve(), quantizer.resolve()
    if not converter.is_file(): raise RuntimeError('llama.cpp converter missing; supply --gguf-converter.')
    if not quantizer.is_file(): raise RuntimeError('llama-quantize missing; supply --gguf-quantizer.')
    if target.exists(): raise RuntimeError('Unrecorded GGUF target already exists; preserve it before exporting again.')
    scratch = gguf_dir / 'tmp'; scratch.mkdir(exist_ok=True)
    export_env = {**os.environ, 'CUDA_VISIBLE_DEVICES': '', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
                  'TMP': str(scratch), 'TEMP': str(scratch), 'TMPDIR': str(scratch)}
    source_files = dict(manifest['artifact_files'])
    tool_hashes = {'converter_sha256': file_sha256(converter), 'quantizer_sha256': file_sha256(quantizer)}
    try:
        subprocess.run([sys.executable, str(converter), str(out / 'merged'), '--outfile', str(intermediate),
                        '--outtype', 'f16', '--use-temp-file'], check=True, env=export_env)
        subprocess.run([str(quantizer), '--max-buffer-size', '128', str(intermediate), str(partial), 'Q4_K_M', '2'],
                       check=True, env=export_env)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f'GGUF export failed (exit {exc.returncode}). See converter/quantizer output above.') from None
    with partial.open('rb') as stream:
        if stream.read(4) != b'GGUF': raise RuntimeError('Converter did not produce a valid GGUF file.')
    if validate_training_manifest(out / 'training_manifest.json')['artifact_files'] != source_files:
        raise ValueError('Merged weights changed during GGUF export.')
    export_hash = file_sha256(partial)
    export = {'path': target.relative_to(out).as_posix(), 'sha256': export_hash,
                               'quantization': 'Q4_K_M', 'source_artifact_files': source_files,
                               'created_at': datetime.now(timezone.utc).isoformat(), 'intermediate_dtype': 'f16',
                               'max_buffer_mib': 128, 'quantizer_threads': 2, **tool_hashes}
    _write_json(pending, export)
    return _finish_gguf_export(out, manifest, export, pending, intermediate, partial, target)


def _created_ollama_identity(create_env, model):
    store = Path(create_env.get('OLLAMA_MODELS') or Path.home() / '.ollama/models').expanduser().resolve()
    parts = model.split('/')
    repository, _, tag = parts[-1].partition(':')
    tag = tag or 'latest'
    prefixes = parts[:-1]
    registry = 'registry.ollama.ai'
    if prefixes and ('.' in prefixes[0] or ':' in prefixes[0] or prefixes[0] == 'localhost'):
        registry = prefixes.pop(0)
    namespace = '/'.join(prefixes) or 'library'
    path = (store / 'manifests' / registry / namespace / repository / tag).resolve()
    if not path.is_relative_to(store) or not path.is_file():
        raise RuntimeError('Created model manifest is missing from the CLI model store; check --ollama-models-dir.')
    raw = path.read_bytes()
    data = json.loads(raw)
    return {'digest': hashlib.sha256(raw).hexdigest(),
            'model_layers': [layer.get('digest') for layer in data.get('layers', [])
                             if layer.get('mediaType') == 'application/vnd.ollama.image.model']}


def resolve_ollama_executable(explicit=None, project_root=None):
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if path.is_file(): return str(path)
        raise RuntimeError('Configured --ollama-executable is not an existing file.')
    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[2]
    portable = root / '.runtime' / 'ollama' / 'ollama.exe'
    if portable.is_file(): return str(portable.resolve())
    installed = shutil.which('ollama')
    if installed: return str(Path(installed).resolve())
    raise RuntimeError('Ollama executable unavailable. Set --ollama-executable or provide .runtime/ollama/ollama.exe; no installation was attempted.')


def register_ollama(output_dir, model='qwen2.5-coder-vitext2sql:3b', base_url='http://127.0.0.1:11434', ollama_executable=None,
                    quantization='int4', models_dir=None):
    out = Path(output_dir).resolve(); manifest = validate_training_manifest(out / 'training_manifest.json')
    if manifest['artifact_kind'] != 'merged': raise ValueError('Merge the adapter before Ollama import.')
    if not model or any(ch.isspace() for ch in model) or model.startswith('-'): raise ValueError('Invalid Ollama model name.')
    if quantization not in ('int4', 'int8', 'nvfp4', 'mxfp4', 'mxfp8', 'q4_K_M'):
        raise ValueError('Unsupported Ollama quantization choice.')
    executable = resolve_ollama_executable(ollama_executable)
    export = manifest.get('gguf_export')
    source = out / export['path'] if export else out / 'merged'
    if export is None and (source / 'config.json').is_file():
        architecture = json.loads((source / 'config.json').read_text(encoding='utf-8')).get('architectures', [])
        if 'Qwen2ForCausalLM' in architecture and quantization in ('int4', 'int8', 'nvfp4', 'mxfp4', 'mxfp8'):
            raise RuntimeError('Qwen2ForCausalLM is unsupported by this Safetensors/MLX import path. '
                               'Run --export-gguf first, then --register-ollama to import the verified GGUF.')
    with urllib.request.urlopen(base_url.rstrip('/') + '/api/tags', timeout=5) as response: before = json.load(response)['models']
    modelfile = out / 'Modelfile'
    modelfile.write_text('FROM "' + source.as_posix() + '"\nPARAMETER temperature 0\nPARAMETER num_ctx 16384\n', encoding='utf-8')
    create_env = {**os.environ, 'OLLAMA_HOST': base_url}
    if models_dir is not None:
        create_env['OLLAMA_MODELS'] = str(Path(models_dir).expanduser().resolve())
    else:
        project_root = Path(__file__).resolve().parents[2]
        portable = project_root / '.runtime' / 'ollama' / 'ollama.exe'
        if not create_env.get('OLLAMA_MODELS') and Path(executable).resolve() == portable.resolve():
            create_env['OLLAMA_MODELS'] = str(project_root / '.runtime' / 'models')
    try:
        command = [executable, 'create', model, '-f', str(modelfile)]
        if export is None: command += ['--quantize', quantization]
        subprocess.run(command, check=True, env=create_env)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f'Ollama create failed (exit {exc.returncode}). See the Ollama error above. '
                           'For unsupported MLX architectures, use --export-gguf before registering.') from None
    created = _created_ollama_identity(create_env, model)
    with urllib.request.urlopen(base_url.rstrip('/') + '/api/tags', timeout=10) as response: after = json.load(response)['models']
    canonical = model if ':' in model else model + ':latest'
    installed = next((item for item in after if item.get('name') in (model, canonical)), None)
    if not installed or not installed.get('digest'): raise RuntimeError('Imported Ollama model could not be verified.')
    if installed['digest'] != created['digest']:
        raise RuntimeError('Ollama server does not expose the created model; check that CLI and server use the same model store.')
    if export and 'sha256:' + export['sha256'] not in created['model_layers']:
        raise RuntimeError('Created model does not contain the verified GGUF export.')
    base_name = manifest.get('base_ollama_model', 'qwen2.5-coder:3b')
    if any(item.get('name') == base_name and item.get('digest') == installed['digest'] for item in before):
        raise ValueError('Imported digest equals the base model; refusing fine-tuned registration.')
    manifest['registration'] = {'model': model, 'digest': installed['digest'], 'registered_at': datetime.now(timezone.utc).isoformat(),
                                'artifact_files': manifest['artifact_files'],
                                'quantization': export['quantization'] if export else quantization}
    if export:
        manifest['registration']['import_artifact'] = {'path': export['path'], 'sha256': export['sha256']}
    _write_json(out / 'training_manifest.json', manifest)
    return manifest['registration']
