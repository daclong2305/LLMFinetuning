"""Private, immutable official ViText2SQL data with database-disjoint splits."""
import hashlib
import json
import re
from pathlib import Path
from .provenance import file_hash,evaluator_fingerprint

REVISION = 'e759141d891feb794bb9a9fb912d544b25583b3c'
SOURCE = 'https://github.com/VinAIResearch/ViText2SQL'
FILES = ('train.json', 'dev.json', 'test.json', 'tables.json')


def quote_identifier(name):
    return '"' + name.replace('"', '""') + '"'


def assert_frozen_database(path):
    path=Path(path)
    for suffix in ('-wal','-journal'):
        sidecar=Path(str(path)+suffix)
        if sidecar.is_file() and sidecar.stat().st_size:
            raise ValueError('SQLite WAL/journal is not a frozen snapshot; checkpoint, close writers and reload dataset.')


class DatasetStore:
    def __init__(self, root, database_dir=None):
        self.root = Path(root)
        self.database_dir = Path(database_dir) if database_dir else self.root / 'database'
        self._samples = {split: [] for split in ('train', 'dev', 'test')}
        self._by_id = {}
        self._db_samples = {}
        self._schemas = {}
        self._tables = {}
        self._database_snapshots = {}
        self._database_errors = {}
        self._snapshot_loading = True
        self._suite = {}
        self._suite_reason = 'Validated test-suite manifest unavailable.'
        self._evaluation_options = {}
        self._summary = {'ready': False, 'state': 'unavailable', 'revision': REVISION,
            'source': SOURCE, 'fingerprint': None, 'split_counts': {}, 'db_counts': {},
            'leakage_audit': {'passed': False}, 'execution_availability': {'available': False,
                'reason': 'Compatible data-filled SQLite databases and gold audit required.'}}
        if not all((self.root / name).is_file() for name in FILES):
            self._summary['reason'] = 'Official dataset not prepared; run scripts/prepare_vitext2sql.py.'
            return
        lock_path = self.root / 'source-lock.json'
        if not lock_path.is_file():
            self._summary['reason'] = 'Missing official dataset source-lock.json integrity manifest.'
            return
        lock = json.loads(lock_path.read_text(encoding='utf-8'))
        if lock.get('revision') != REVISION:
            raise ValueError('Dataset revision does not match pinned official source.')
        hashes = {name: hashlib.sha256((self.root / name).read_bytes()).hexdigest() for name in FILES}
        if hashes != lock.get('sha256'):
            raise ValueError('Dataset source hash integrity check failed.')
        self._summary['fingerprint'] = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
        self._summary['source_hashes'] = hashes
        self._summary['source_fingerprint'] = self._summary['fingerprint']
        for table in json.loads((self.root / 'tables.json').read_text(encoding='utf-8')):
            self._tables[table['db_id']] = table
            self._schemas[table['db_id']] = self._build_schema(table)
        from .vendor.spider.evaluation import Evaluator
        db_sets = {}
        for split in self._samples:
            rows = json.loads((self.root / (split + '.json')).read_text(encoding='utf-8'))
            db_sets[split] = set()
            for index, row in enumerate(rows):
                db = row['db_id']
                if db not in self._schemas:
                    raise ValueError('Sample references unknown database: ' + db)
                difficulty = Evaluator().eval_hardness(row['sql']) if row.get('sql') else 'unknown'
                sample = {'id': f'{split}:{index:05d}', 'split': split, 'db_id': db,
                    'question': row['question'], 'gold_sql': row['query'], 'difficulty': difficulty}
                self._samples[split].append(sample)
                self._by_id[sample['id']] = sample
                self._db_samples.setdefault(db, []).append(sample)
                db_sets[split].add(db)
        overlaps = {a + '/' + b: sorted(db_sets[a] & db_sets[b])
                    for a, b in (('train', 'dev'), ('train', 'test'), ('dev', 'test'))}
        if any(overlaps.values()):
            raise ValueError('Database-disjoint split leakage overlap: ' + json.dumps(overlaps))
        self._summary.update(ready=True, state='ready',
            split_counts={s: len(v) for s, v in self._samples.items()},
            db_counts={s: len(v) for s, v in db_sets.items()},
            leakage_audit={'passed': True, 'overlaps': overlaps})
        present = sum(self._find_database(db) is not None for db in self._schemas)
        self._summary['execution_availability']['database_files_present'] = present
        self._summary['execution_availability']['total_databases'] = len(self._schemas)
        database_hashes = {}
        for db in self._schemas:
            try:
                path = self.database_path(db)
            except ValueError as exc:
                self._database_errors[db]=str(exc)
                continue
            if path is not None:
                digest = hashlib.sha256()
                with path.open('rb') as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                        digest.update(chunk)
                database_hashes[db] = digest.hexdigest()
                stat = path.stat()
                self._database_snapshots[db] = (str(path.resolve()), stat.st_size, stat.st_mtime_ns, database_hashes[db])
        self._snapshot_loading = False
        self._summary['database_errors'] = dict(self._database_errors)
        self._summary['database_hashes'] = database_hashes
        if database_hashes:
            self._summary['fingerprint'] = hashlib.sha256(json.dumps(
                {'source': hashes, 'sqlite': database_hashes}, sort_keys=True).encode()).hexdigest()
        for filename, field, fingerprint in (
            ('gold-parse-audit.json', 'gold_parse_audit', self._summary['source_fingerprint']),
            ('execution-audit.json', 'execution_audit', self._summary['fingerprint'])):
            audit_path = self.root / filename
            if audit_path.is_file():
                try:
                    audit = json.loads(audit_path.read_text(encoding='utf-8'))
                    if audit.get('fingerprint') == fingerprint and audit.get('evaluator_fingerprint')==evaluator_fingerprint():
                        self._summary[field] = {k: v for k, v in audit.items() if k != 'failures'}
                except (OSError, ValueError):
                    pass
        execution_audit = self._summary.get('execution_audit', {})
        if execution_audit:
            availability = self._summary['execution_availability']
            availability['validated_db_ids'] = execution_audit.get('validated_db_ids', [])
            availability['available'] = bool(availability['validated_db_ids'])
            availability['reason'] = None if availability['available'] else 'No database passed complete gold execution audit.'
        self._load_optional_metric_assets()

    def _load_optional_metric_assets(self):
        options_path = self.root / 'evaluation-options.json'
        if options_path.is_file():
            try:
                options = json.loads(options_path.read_text(encoding='utf-8'))
                if not isinstance(options, dict):
                    raise ValueError('Evaluation options must be a JSON object')
                self._evaluation_options = options
            except (OSError, ValueError) as exc:
                self._evaluation_options = {'error': str(exc)}
        manifest_path = self.root / 'test-suite-manifest.json'
        manifest = None
        try:
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                if manifest.get('version') != 1 or manifest.get('dataset_fingerprint') != self._summary['fingerprint']:
                    raise ValueError('Test-suite manifest version/dataset fingerprint mismatch')
                provenance = manifest.get('provenance')
                if not isinstance(provenance, dict) or not all(isinstance(provenance.get(k), str) and provenance[k].strip() for k in ('source', 'description')):
                    raise ValueError('Test-suite provenance source and description required')
                entries = manifest.get('files')
                if not isinstance(entries, list) or not entries or len(entries) > 1024:
                    raise ValueError('Test-suite files must be a nonempty bounded list')
                suite = {}
                for entry in entries:
                    db_id = entry.get('db_id')
                    if db_id not in self._schemas:
                        raise ValueError('Test-suite references unknown database')
                    relative = Path(entry['path'])
                    path = (self.root / relative).resolve()
                    if relative.is_absolute() or not path.is_relative_to(self.root.resolve()) or not path.is_file():
                        raise ValueError('Test-suite path must name a file safely beneath dataset root')
                    assert_frozen_database(path)
                    expected = entry.get('sha256', '')
                    if not isinstance(expected, str) or not re.fullmatch(r'[a-f0-9]{64}', expected):
                        raise ValueError('Test-suite SHA-256 required')
                    digest = hashlib.sha256()
                    with path.open('rb') as handle:
                        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                            digest.update(chunk)
                    if digest.hexdigest() != expected:
                        raise ValueError('Test-suite file hash integrity failed')
                    stat = path.stat()
                    suite.setdefault(db_id, []).append({'path': path, 'sha256': expected,
                        'snapshot': (stat.st_size, stat.st_mtime_ns)})
                self._suite = suite
                self._suite_reason = None
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            self._suite = {}
            self._suite_reason = str(exc)
        eligible = [db for db, entries in self._suite.items() if len({e['sha256'] for e in entries}) >= 2]
        self._summary['test_suite'] = {'available': bool(eligible), 'eligible_db_ids': eligible,
            'reason': self._suite_reason if self._suite_reason else (None if eligible else 'At least two distinct test-suite states required per database.'),
            'validation': 'File hashes/provenance validated; schema, data states and gold SQL audited at evaluation.'}
        profile = {'manifest': manifest, 'options': self._evaluation_options}
        self._summary['metric_assets_fingerprint'] = hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()
        self._summary['evaluation_options'] = dict(self._evaluation_options)

    def test_suite_assets(self, db_id):
        entries = self._suite.get(db_id, [])
        if self._suite_reason:
            return {'available': False, 'reason': self._suite_reason, 'files': []}
        if len({e['sha256'] for e in entries}) < 2:
            return {'available': False, 'reason': 'At least two distinct test-suite states required for this database.', 'files': []}
        for entry in entries:
            try:
                assert_frozen_database(entry['path'])
            except ValueError as exc:
                return {'available':False,'reason':str(exc),'files':[]}
            stat = entry['path'].stat()
            if (stat.st_size, stat.st_mtime_ns) != entry['snapshot'] or file_hash(entry['path'])!=entry['sha256']:
                return {'available': False, 'reason': 'Test-suite file changed after immutable snapshot.', 'files': []}
        return {'available': True, 'reason': None, 'files': [dict(e) for e in entries]}

    def evaluation_options(self):
        return dict(self._evaluation_options)

    @staticmethod
    def _build_schema(table):
        schema = {}
        names = table['table_names_original']
        cols = table['column_names_original']
        types = {'number': 'NUMERIC', 'text': 'TEXT', 'time': 'TEXT', 'boolean': 'INTEGER', 'others': 'BLOB'}
        for ti, name in enumerate(names):
            columns = [{'name': col, 'type': types.get(table['column_types'][ci], 'TEXT'),
                        'pk': ci in table.get('primary_keys', [])}
                       for ci, (ct, col) in enumerate(cols) if ct == ti]
            foreign = []
            for a, b in table.get('foreign_keys', []):
                if cols[a][0] == ti:
                    foreign.append({'table': names[cols[b][0]], 'from': cols[a][1], 'to': cols[b][1]})
            pieces = [quote_identifier(c['name']) + ' ' + c['type'] for c in columns]
            pk = [quote_identifier(c['name']) for c in columns if c['pk']]
            if pk:
                pieces.append('PRIMARY KEY (' + ', '.join(pk) + ')')
            for fk in foreign:
                pieces.append('FOREIGN KEY (' + quote_identifier(fk['from']) + ') REFERENCES ' +
                              quote_identifier(fk['table']) + '(' + quote_identifier(fk['to']) + ')')
            schema[name] = {'columns': columns, 'foreign_keys': foreign, 'description': '',
                'ddl': 'CREATE TABLE ' + quote_identifier(name) + ' (' + ', '.join(pieces) + ');'}
        return schema

    def summary(self):
        return json.loads(json.dumps(self._summary))

    def samples(self, split, limit=None):
        if split not in self._samples:
            raise ValueError('Unknown dataset split')
        return [dict(s) for s in self._samples[split][:limit]]

    def get_sample(self, sample_id):
        if sample_id not in self._by_id:
            raise KeyError('Unknown dataset sample')
        return dict(self._by_id[sample_id])

    def samples_for_database(self, db_id):
        return [dict(s) for s in self._db_samples.get(db_id, [])]

    def schema(self, db_id):
        if db_id not in self._schemas:
            raise KeyError('Unknown dataset database')
        return json.loads(json.dumps(self._schemas[db_id]))

    def _find_database(self, db_id):
        if db_id not in self._schemas:
            return None
        for path in (self.database_dir / db_id / (db_id + '.sqlite'), self.database_dir / (db_id + '.sqlite')):
            if path.is_file() and path.resolve().is_relative_to(self.database_dir.resolve()):
                return path
        return None

    def database_path(self,db_id):
        path=self._find_database(db_id)
        if path is None:
            if db_id in self._database_snapshots:
                raise ValueError('SQLite database removed after snapshot; reload dataset.')
            return None
        assert_frozen_database(path)
        if db_id in self._database_errors:
            raise ValueError(self._database_errors[db_id])
        snapshot=self._database_snapshots.get(db_id)
        if snapshot:
            stat=path.stat()
            if snapshot!=(str(path.resolve()),stat.st_size,stat.st_mtime_ns,file_hash(path)):
                raise ValueError('SQLite database changed after dataset snapshot; reload dataset before evaluation.')
        elif not self._snapshot_loading:
            raise ValueError('SQLite database not included in snapshot; reload dataset before evaluation.')
        return path
