"""Acquire pinned official ViText2SQL privately; never create empty benchmark DBs."""
import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from text2sql_demo.experiment.dataset import DatasetStore, FILES, REVISION, SOURCE
from text2sql_demo.experiment.evaluation import parse_structural, _audit_database
from text2sql_demo.experiment.provenance import evaluator_fingerprint

OFFICIAL_HASHES = {
    'train.json': '518831475f87189e30f538f7387fb01b9b4afe923b2556ab19aadfd1013d9902',
    'dev.json': 'a402e1a2ffb40bd3ba33e3a1c7e5ee2413325390e16d85b1a5bb1cafa357aa88',
    'test.json': '4c550cee47518ffa160df068f5983093bd4cc6f863975c724ceae12f7277cc13',
    'tables.json': '7ecabf6da309574f1894c017692b15d13700c99745452b2f51397ce2a6465228'}


def prepare(root, offline=False):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    hashes = {}
    urls = {}
    for name in FILES:
        url = f'https://raw.githubusercontent.com/VinAIResearch/ViText2SQL/{REVISION}/data/syllable-level/{name}'
        path = root / name
        if not offline:
            raw = urllib.request.urlopen(url, timeout=120).read()
            json.loads(raw.decode('utf-8'))
            path.write_bytes(raw)
        if not path.is_file():
            raise ValueError('Offline source file missing: ' + name)
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        if hashes[name] != OFFICIAL_HASHES[name]:
            raise ValueError('Source bytes do not match pinned official hash: ' + name)
        urls[name] = url
    manifest = {'source': SOURCE, 'revision': REVISION, 'representation': 'syllable-level',
                'urls': urls, 'sha256': hashes,
                'usage_note': 'Official source data kept private; consult source repository usage terms. No SQLite files supplied.'}
    existing = root / 'source-lock.json'
    if existing.is_file():
        previous = json.loads(existing.read_text(encoding='utf-8'))
        if previous.get('sha256') != hashes or previous.get('revision') != REVISION:
            raise ValueError('Existing immutable source lock does not match downloaded/offline bytes')
    existing.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return DatasetStore(root)


def audit_gold(store):
    report = {'fingerprint': store.summary().get('source_fingerprint', store.summary()['fingerprint']), 'revision': REVISION,
              'evaluator_fingerprint':evaluator_fingerprint(),'by_split': {}, 'failures': []}
    for split in ('train', 'dev', 'test'):
        samples = store.samples(split)
        passed = 0
        for sample in samples:
            try:
                parse_structural(sample['gold_sql'], store.schema(sample['db_id']))
                passed += 1
            except (AssertionError, ValueError, KeyError, IndexError, TypeError, RecursionError) as exc:
                report['failures'].append({'id': sample['id'], 'db_id': sample['db_id'], 'error': str(exc)})
        report['by_split'][split] = {'total': len(samples), 'parsed': passed, 'failed': len(samples) - passed}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1] / '.runtime/datasets/vitext2sql'))
    parser.add_argument('--offline', action='store_true', help='Lock already acquired official source bytes')
    parser.add_argument('--audit-gold', action='store_true', help='Parse every gold SQL and write private gold-parse-audit.json')
    parser.add_argument('--audit', action='store_true', help='Audit gold parsing and compatible data-filled SQLite execution')
    parser.add_argument('--database-dir', help='Existing data-filled Vietnamese-schema SQLite directory')
    args = parser.parse_args()
    store = prepare(args.root, args.offline)
    if args.database_dir:
        store = DatasetStore(args.root, args.database_dir)
    print(json.dumps(store.summary(), ensure_ascii=True, indent=2))
    if args.audit_gold or args.audit:
        report = audit_gold(store)
        (Path(args.root) / 'gold-parse-audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report['by_split'], indent=2))
    if args.audit:
        audit = {'fingerprint': store.summary()['fingerprint'],'evaluator_fingerprint':evaluator_fingerprint(), 'validated_db_ids': [], 'unavailable': {}}
        db_ids = sorted({s['db_id'] for split in ('train', 'dev', 'test') for s in store.samples(split)})
        for db_id in db_ids:
            try:
                path = store.database_path(db_id)
            except (ValueError,OSError) as exc:
                audit['unavailable'][db_id]=str(exc)
                continue
            if path is None:
                audit['unavailable'][db_id] = 'Compatible data-filled SQLite database unavailable.'
                continue
            valid, reason = _audit_database(path, store.schema(db_id), store.samples_for_database(db_id)[0], store, 5)
            if valid:
                audit['validated_db_ids'].append(db_id)
            else:
                audit['unavailable'][db_id] = reason
        (Path(args.root) / 'execution-audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'execution_databases_validated': len(audit['validated_db_ids']),
                          'execution_databases_unavailable': len(audit['unavailable'])}))


if __name__ == '__main__':
    main()
