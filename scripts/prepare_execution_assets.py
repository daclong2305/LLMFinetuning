"""Privately adapt published Spider SQLite assets to pinned ViText2SQL identifiers.

This does not generate data or alter question/SQL labels. Run --help for usage.
"""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import uuid
import zipfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from text2sql_demo.experiment.dataset import DatasetStore, quote_identifier, assert_frozen_database
from text2sql_demo.experiment.evaluation import _audit_database, _state_fingerprint, evaluate_prediction
from text2sql_demo.experiment.provenance import file_hash, evaluator_fingerprint


def alignment(source, target):
    """Return table/column index mappings, rejecting structural disagreement."""
    if source['db_id'] != target['db_id']:
        raise ValueError('Database IDs do not align')
    if len(source['table_names_original']) != len(target['table_names_original']):
        raise ValueError('Table counts do not align')
    a, b = source['column_names_original'], target['column_names_original']
    if len(a) != len(b) or [c[0] for c in a] != [c[0] for c in b]:
        raise ValueError('Column positions do not align')
    if source['column_types'] != target['column_types']:
        raise ValueError('Column type annotations do not align')
    for key in ('primary_keys', 'foreign_keys'):
        if sorted(source.get(key, [])) != sorted(target.get(key, [])):
            raise ValueError(key + ' annotations do not align')
    tables = list(zip(source['table_names_original'], target['table_names_original']))
    if len({new.casefold() for _, new in tables}) != len(tables):
        raise ValueError('Duplicate target table names')
    result = []
    for index, (old, new) in enumerate(tables):
        columns = [(left[1], right[1]) for left, right in zip(a, b) if left[0] == index]
        if len({c[1].casefold() for c in columns}) != len(columns):
            raise ValueError('Duplicate target column names')
        result.append((old, new, columns))
    return result


def adapt_database(source_path, output_path, source_schema, target_schema):
    """Copy/rename a database atomically, preserving source types, indexes and rows.

    Published schema indices establish the mapping; actual source columns must
    match the metadata. No coercion, cell translation, or synthetic rows.
    """
    source_path, output_path = Path(source_path), Path(output_path)
    if output_path.exists():
        raise FileExistsError(output_path)
    mapping = alignment(source_schema, target_schema)
    assert_frozen_database(source_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    token = '__vi_' + uuid.uuid4().hex
    stage = output_path.with_name(output_path.name + '.' + token + '.tmp')
    try:
        with closing(sqlite3.connect(source_path.resolve().as_uri() + '?mode=ro', uri=True)) as src:
            src.execute('PRAGMA query_only=ON')
            expected_tables = {t[0].casefold() for t in mapping}
            actual_tables = {r[0].casefold() for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")
                             if not r[0].casefold().startswith('sqlite_') or r[0].casefold() in expected_tables}
            if actual_tables != expected_tables:
                raise ValueError('Source tables do not align with published schema')
            for old, new, columns in mapping:
                actual = {r[1].casefold() for r in src.execute('PRAGMA table_info(' + quote_identifier(old) + ')')}
                if actual != {c[0].casefold() for c in columns}:
                    raise ValueError('Source columns do not align: ' + old)
            with closing(sqlite3.connect(stage)) as dest:
                src.backup(dest)
                with dest:
                    # Python's sqlite3 does not implicitly BEGIN for ALTER TABLE.
                    # One transaction avoids a disk sync for every renamed column.
                    dest.execute('BEGIN IMMEDIATE')
                    working_mapping = []
                    for ti, (old, new, columns) in enumerate(mapping):
                        if old.casefold().startswith('sqlite_'):
                            # SQLite owns this table and forbids ALTER TABLE on it.
                            # Preserve the published rows in a normal user table
                            # before SQLite updates its internal sequence names.
                            snapshot_name = token + '_system' + str(ti)
                            dest.execute('CREATE TABLE ' + quote_identifier(snapshot_name) + ' AS SELECT * FROM ' + quote_identifier(old))
                            working_mapping.append((snapshot_name, new, columns))
                        else:
                            working_mapping.append((old, new, columns))
                    for ti, (old, new, columns) in enumerate(working_mapping):
                        for ci, (before, after) in enumerate(columns):
                            dest.execute('ALTER TABLE ' + quote_identifier(old) + ' RENAME COLUMN ' + quote_identifier(before) + ' TO ' + quote_identifier(token + '_c' + str(ci)))
                        for ci, (before, after) in enumerate(columns):
                            dest.execute('ALTER TABLE ' + quote_identifier(old) + ' RENAME COLUMN ' + quote_identifier(token + '_c' + str(ci)) + ' TO ' + quote_identifier(after))
                    for ti, (old, new, columns) in enumerate(working_mapping):
                        dest.execute('ALTER TABLE ' + quote_identifier(old) + ' RENAME TO ' + quote_identifier(token + '_t' + str(ti)))
                    for ti, (old, new, columns) in enumerate(working_mapping):
                        dest.execute('ALTER TABLE ' + quote_identifier(token + '_t' + str(ti)) + ' RENAME TO ' + quote_identifier(new))
                if dest.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Adapted SQLite integrity check failed')
                # Compare raw tuples, including NULL and SQLite storage classes.
                src.text_factory = bytes
                dest.text_factory = bytes
                for old, new, columns in mapping:
                    source_rows = src.execute('SELECT * FROM ' + quote_identifier(old))
                    target_rows = dest.execute('SELECT * FROM ' + quote_identifier(new))
                    while True:
                        left, right = source_rows.fetchmany(4096), target_rows.fetchmany(4096)
                        if left != right:
                            raise ValueError('Source data changed during adaptation')
                        if not left:
                            break
        # Windows rename fails when another importer created the target meanwhile.
        if output_path.exists():
            raise FileExistsError(output_path)
        stage.rename(output_path)
    finally:
        stage.unlink(missing_ok=True)


def write_json(path, value):
    path = Path(path)
    stage = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        stage.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(stage, path)
    finally:
        stage.unlink(missing_ok=True)


def archive_member(archive, member, workspace):
    """Extract one known member to a private fixed filename, never arbitrary paths."""
    info = archive.getinfo(member)
    if info.file_size > 512 * 1024 * 1024:
        raise ValueError('SQLite source member exceeds 512 MiB bound')
    path = workspace / 'source.sqlite'
    with archive.open(info) as source, path.open('wb') as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    return path


def source_record(sources, name):
    path = sources / name
    lock = json.loads((sources / (name + '.source.json')).read_text(encoding='utf-8'))
    # Stream large archives instead of loading a gigabyte into memory.
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != lock['sha256']:
        raise ValueError('Acquired source hash changed: ' + name)
    return lock


def prepare_assets(root, sources, splits=('dev', 'test', 'train'), with_suites=True):
    root, sources = Path(root), Path(sources)
    store = DatasetStore(root)
    if not store.summary()['ready']:
        raise ValueError('Prepare pinned ViText2SQL JSON source first')
    target_tables = {t['db_id']: t for t in json.loads((root / 'tables.json').read_text(encoding='utf-8'))}
    dbs = sorted({s['db_id'] for split in splits for s in store.samples(split)})
    names = ['spider_data.zip'] + (['testsuitedatabases.zip', 'suite-tables.json'] if with_suites else [])
    provenance = {name: source_record(sources, name) for name in names}
    report_path = root / 'execution-assets-import.json'
    previous = json.loads(report_path.read_text(encoding='utf-8')) if report_path.is_file() else {}
    report = {'version': 1, 'policy': 'source_rows_preserved_identifier_rename_v1',
        'sources': provenance, 'splits': list(splits), 'databases': dict(previous.get('databases', {})),
        'test_suites': dict(previous.get('test_suites', {})),
        'limitations': ['Local adapted EX/TS/VES; not an official ViText2SQL leaderboard score.',
            'No cell translation or gold label repair; source/schema conflicts remain unavailable.']}
    with zipfile.ZipFile(sources / 'spider_data.zip') as original, tempfile.TemporaryDirectory(dir=root) as td:
        workspace = Path(td)
        metadata = [n for n in original.namelist() if n.endswith('/tables.json') and not n.startswith('__MACOSX/')]
        if len(metadata) != 1:
            raise ValueError('Expected one published Spider tables.json')
        english = {t['db_id']: t for t in json.loads(original.read(metadata[0]))}
        members = {n.split('/')[-2]: n for n in original.namelist()
                   if '/database/' in n and n.endswith('.sqlite') and not n.startswith('__MACOSX/')}
        for db in dbs:
            try:
                output = root / 'database' / db / (db + '.sqlite')
                if db not in english or db not in members:
                    raise ValueError('Published original database/schema missing')
                source = archive_member(original, members[db], workspace)
                source_hash = file_hash(source)
                # Reruns trust only exact previous outputs from these exact inputs.
                old = previous.get('databases', {}).get(db, {})
                if output.exists() and old.get('sha256') == file_hash(output) and old.get('source_sha256') == source_hash:
                    report['databases'][db] = old
                    continue
                if output.exists():
                    with closing(sqlite3.connect(output.resolve().as_uri() + '?mode=ro', uri=True)) as con:
                        demo = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='__visql_demo'").fetchone()
                    if not demo:
                        raise FileExistsError('Existing untracked database preserved: ' + str(output))
                staged = workspace / 'adapted.sqlite'
                staged.unlink(missing_ok=True)
                adapt_database(source, staged, english[db], target_tables[db])
                if output.exists():
                    backup = root / 'demo-backups' / (db + '-' + file_hash(output) + '.sqlite')
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    if not backup.exists():
                        shutil.copy2(output, backup)
                    if file_hash(backup) != file_hash(output):
                        raise ValueError('Demo backup verification failed')
                output.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged, output)
                report['databases'][db] = {'path': output.relative_to(root).as_posix(),
                    'sha256': file_hash(output), 'source_member': members[db], 'source_sha256': source_hash,
                    'mapping': alignment(english[db], target_tables[db])}
                print('database', db, 'imported', flush=True)
            except (ValueError, OSError, sqlite3.Error, KeyError) as exc:
                report['databases'][db] = {'reason': str(exc)}
                print('database', db, 'unavailable:', str(exc), flush=True)
            write_json(report_path, report)

        if with_suites:
            suite_schema = {t['db_id']: t for t in json.loads((sources / 'suite-tables.json').read_text(encoding='utf-8'))}
            with zipfile.ZipFile(sources / 'testsuitedatabases.zip') as suites:
                by_db = {}
                for name in suites.namelist():
                    pieces = name.split('/')
                    if len(pieces) == 3 and pieces[0] == 'database' and name.endswith('.sqlite'):
                        by_db.setdefault(pieces[1], []).append(name)
                for db in dbs:
                    imported, errors = [], []
                    # Keep provenance for all previously published states while
                    # revalidating a rerun; interruption must not orphan the
                    # states that have not been visited yet on this pass.
                    checkpoint_files = list(previous.get('test_suites', {}).get(db, {}).get('files', []))
                    report['test_suites'][db] = {'files': checkpoint_files, 'errors': errors, 'complete': False,
                        'reason': 'Import in progress; not eligible until every published state is processed.'}
                    for member in sorted(by_db.get(db, [])):
                        try:
                            output = root / 'test-suite' / db / Path(member).name
                            old_entries = previous.get('test_suites', {}).get(db, {}).get('files', [])
                            old = next((f for f in old_entries if f['path'] == output.relative_to(root).as_posix()), None)
                            if output.exists():
                                if old and old['sha256'] == file_hash(output):
                                    imported.append(old)
                                    write_json(report_path, report)
                                    continue
                                raise FileExistsError('Existing untracked suite state preserved')
                            source = archive_member(suites, member, workspace)
                            adapt_database(source, output, suite_schema[db], target_tables[db])
                            entry = {'db_id': db, 'path': output.relative_to(root).as_posix(),
                                'sha256': file_hash(output), 'source_member': member, 'source_sha256': file_hash(source)}
                            imported.append(entry)
                            checkpoint_files[:] = [f for f in checkpoint_files if f['path'] != entry['path']]
                            checkpoint_files.append(entry)
                        except (ValueError, OSError, sqlite3.Error, KeyError) as exc:
                            errors.append({'source_member': member, 'reason': str(exc)})
                        write_json(report_path, report)
                    report['test_suites'][db] = {'files': imported, 'errors': errors,
                        'complete': True,
                        'reason': None if imported else 'No compatible published suite states for this schema.'}
                    print('suite', db, len(imported), 'states;', len(errors), 'incompatible', flush=True)
                    write_json(report_path, report)
    write_json(report_path, report)
    return report


def audit_assets(root, self_check=False):
    """Audit real assets, build a manifest of whole valid suites, expose coverage."""
    root = Path(root)
    report = json.loads((root / 'execution-assets-import.json').read_text(encoding='utf-8'))
    store = DatasetStore(root)
    audit = {'fingerprint': store.summary()['fingerprint'], 'evaluator_fingerprint': evaluator_fingerprint(),
        'validated_db_ids': [], 'unavailable': {}}
    readiness = {'policy': 'local_adapted_execution_metrics', 'databases': {}, 'coverage': {},
        'self_checks': [], 'note': 'Gold self-checks verify evaluator/assets; they are not model benchmark results.'}
    manifest_files = []
    for db, info in report['databases'].items():
        schema, samples = store.schema(db), store.samples_for_database(db)
        details = {'ex': False, 'ts': False}
        try:
            path = store.database_path(db)
            if path is None:
                raise ValueError(info.get('reason', 'Base database missing'))
            if not info.get('sha256') or info.get('path') != path.relative_to(root).as_posix():
                raise ValueError('Verified published-source import provenance unavailable for base database')
            if file_hash(path) != info['sha256']:
                raise ValueError('Base database hash changed after verified source import')
            valid, reason = _audit_database(path, schema, samples[0], store, 5)
            if not valid:
                raise ValueError(reason)
            details['ex'] = True
            audit['validated_db_ids'].append(db)
        except (ValueError, OSError, sqlite3.Error) as exc:
            audit['unavailable'][db] = str(exc)
            details['ex_reason'] = str(exc)
        entries = report.get('test_suites', {}).get(db, {}).get('files', [])
        try:
            suite_info = report.get('test_suites', {}).get(db, {})
            if suite_info.get('complete') is False or suite_info.get('errors'):
                raise ValueError('Published suite import incomplete or contains incompatible states; partial suites are not scored')
            if len(entries) < 2:
                raise ValueError('At least two compatible published suite states unavailable')
            states = set()
            for entry in entries:
                path = root / entry['path']
                if file_hash(path) != entry['sha256']:
                    raise ValueError('Imported suite state hash changed')
                valid, reason = _audit_database(path, schema, samples[0], store, 5)
                if not valid:
                    raise ValueError(reason)
                states.add(_state_fingerprint(path, schema, 5))
            if len(states) < 2:
                raise ValueError('Suite lacks two distinct actual data states')
            manifest_files.extend({k: e[k] for k in ('db_id', 'path', 'sha256')} for e in entries)
            details.update(ts=True, suite_states=len(entries), distinct_data_states=len(states))
        except (ValueError, OSError, sqlite3.Error) as exc:
            details['ts_reason'] = str(exc)
        readiness['databases'][db] = details
        print('audit', db, 'EX', details['ex'], 'TS', details['ts'], flush=True)
        write_json(root / 'execution-assets-readiness.json', readiness)
    if len(manifest_files) > 1024:
        raise ValueError('Full published suites exceed the existing manifest limit; do not silently truncate suites')
    write_json(root / 'execution-audit.json', audit)
    write_json(root / 'test-suite-manifest.json', {'version': 1, 'dataset_fingerprint': store.summary()['fingerprint'],
        'provenance': {'source': 'https://github.com/taoyds/test-suite-sql-eval/tree/e97acc546ecbee8fa27fa8dbf025ef61493a876c',
            'description': 'Published full compatible suites, identifiers renamed by aligned schema indices. Source hashes, mappings and exclusions in execution-assets-import.json. No generated states or inferred cell translations.'},
        'files': manifest_files})
    write_json(root / 'evaluation-options.json', {'ves_repeats': 100, 'ves_budget_s': 60})
    for split in ('train', 'dev', 'test'):
        samples = store.samples(split)
        measured = {metric: sum(readiness['databases'].get(s['db_id'], {}).get(metric, False) for s in samples) for metric in ('ex', 'ts')}
        readiness['coverage'][split] = {'total': len(samples), **measured, 'ves_eligible': measured['ex']}
    if self_check:
        store = DatasetStore(root)
        for db, details in readiness['databases'].items():
            if not details['ex']:
                continue
            sample = store.samples_for_database(db)[0]
            good = evaluate_prediction(sample['gold_sql'], sample, store)
            bad = evaluate_prediction('SELECT * FROM "__missing_negative_control__"', sample, store)
            readiness['self_checks'].append({'db_id': db, 'sample_id': sample['id'],
                'gold': {k: good[k] for k in ('ex', 'ts', 'ves')}, 'gold_unavailable_reasons': good['unavailable_reasons'],
                'gold_ves_completed_pairs': good.get('ves_details', {}).get('completed_pairs'),
                'negative_control': {k: bad[k] for k in ('ex', 'ts', 'ves')}})
            print('self-check', db, 'EX', good['ex'], 'TS', good['ts'], 'VES', good['ves'], flush=True)
    readiness['dataset_fingerprint'] = store.summary()['fingerprint']
    write_json(root / 'execution-assets-readiness.json', readiness)
    return readiness


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT / '.runtime/datasets/vitext2sql')
    parser.add_argument('--sources', type=Path, default=ROOT / '.runtime/metric-sources')
    parser.add_argument('--splits', nargs='+', choices=('train', 'dev', 'test'), default=['dev', 'test', 'train'])
    parser.add_argument('--without-suites', action='store_true')
    parser.add_argument('--audit-only', action='store_true')
    parser.add_argument('--self-check', action='store_true', help='Gold and negative evaluator checks; no model inference')
    args = parser.parse_args()
    if not args.audit_only:
        prepare_assets(args.root, args.sources, args.splits, not args.without_suites)
    readiness = audit_assets(args.root, args.self_check)
    print(json.dumps(readiness['coverage'], indent=2))


if __name__ == '__main__':
    main()
