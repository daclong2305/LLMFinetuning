"""Attributed Spider structural metrics and complete bounded SQLite scoring."""
import copy
import hashlib
import json
import math
import re
import sqlite3
import time
from collections import Counter
from contextlib import closing
from pathlib import Path

from .dataset import quote_identifier,assert_frozen_database
from .vendor.spider import process_sql as parser
from .vendor.spider import evaluation as spider

_AUDITS = {}
_STATE_FINGERPRINTS = {}


def _identifiers(schema):
    names = list(schema)
    for table in schema.values():
        names.extend(c['name'] for c in table['columns'])
    return {name.casefold(): 'u' + str(i) for i, name in enumerate(dict.fromkeys(names))}


def _rewrite(sql, schema, canonical=True):
    """Map known multiword identifiers without replacing SQL string literals."""
    if not isinstance(sql, str):
        return ''
    names = _identifiers(schema)
    scoped_columns = set()
    for table, info in schema.items():
        forms = '(?:' + re.escape(table) + '|' + re.escape(quote_identifier(table)) + ')'
        if re.search(r'\b(?:from|join)\s+' + forms + r'(?![\w])', sql, re.I):
            scoped_columns.update(c['name'].casefold() for c in info['columns'])
    alternatives = '|'.join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    known = re.compile(r'(?<![\w])(' + alternatives + r')(?![\w])', re.I) if names else None
    chunks = re.findall(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[[^\]]*\]|[^'\"`\[]+", sql)
    if ''.join(chunks) != sql:
        if canonical:
            raise ValueError('Unclosed SQL quote')
        return sql
    aliases = {}
    if canonical:
        table_forms = '|'.join(re.escape(t) + '|' + re.escape(quote_identifier(t)) for t in schema)
        for index, chunk in enumerate(chunks):
            implicit = index and bool(re.search(r'\b(?:from|join)\s+(?:' + table_forms + r')\s+$', ''.join(chunks[:index]), re.I))
            if chunk.startswith('"') and index and (re.search(r'\bas\s*$', chunks[index - 1], re.I) or implicit):
                aliases[chunk[1:-1].replace('""', '"').casefold()] = 'alias' + str(len(aliases))
    out = []
    for index, chunk in enumerate(chunks):
        if chunk.startswith("'"):
            out.append(chunk)
        elif chunk[0] in ('"', '`', '['):
            name = chunk[1:-1].replace('""', '"').replace('``', '`')
            if name.casefold() in aliases and (re.search(r'\bas\s*$', ''.join(out), re.I) or
                    re.search(r'\b(?:from|join)\s+u\d+\s+$', ''.join(out), re.I) or
                    (index + 1 < len(chunks) and chunks[index + 1].lstrip().startswith('.'))):
                out.append(aliases[name.casefold()])
                continue
            # SQLite resolves a known double-quoted schema name as an
            # identifier, including the right-hand side of a predicate.
            value_position = bool(re.search(r'(?:=|!=|<>|>=|<=|>|<|\blike|\bbetween)\s*$', ''.join(out), re.I))
            literal = chunk[0] == '"' and value_position and name.casefold() not in scoped_columns
            if name.casefold() in names and not literal:
                out.append(names[name.casefold()] if canonical else quote_identifier(name))
            else:
                out.append(chunk)
        elif known:
            if canonical:
                for alias, token in aliases.items():
                    chunk = re.sub(r'(?<![\w])' + re.escape(alias) + r'(?=\s*\.)', token, chunk, flags=re.I)
            out.append(known.sub(lambda m: names[m.group(0).casefold()] if canonical else quote_identifier(m.group(0)), chunk))
        else:
            out.append(chunk)
    return ''.join(out)


def executable_sql(sql, schema):
    """Quote official raw syllable-level identifiers for compatible SQLite."""
    return _rewrite(sql, schema, canonical=False)


def compile_readonly_sql(sql, schema):
    """Validate against empty schema; never use empty results as accuracy."""
    if not isinstance(sql,str) or not sql.strip() or len(sql)>20000 or not re.match(r'^\s*(SELECT|WITH)\b',sql,re.I):
        return False,'A single bounded SELECT/WITH query is required.'
    allowed={sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION,sqlite3.SQLITE_RECURSIVE}
    denied={'load_extension','readfile','writefile','eval','randomblob','zeroblob','printf','format'}
    try:
        with closing(sqlite3.connect(':memory:')) as con:
            for name,table in schema.items():
                columns=', '.join(quote_identifier(c['name'])+' TEXT' for c in table['columns'])
                con.execute('CREATE TABLE '+quote_identifier(name)+' ('+columns+')')
            con.set_authorizer(lambda action,a,b,db,src: sqlite3.SQLITE_OK if action in allowed and not(action==sqlite3.SQLITE_FUNCTION and (b or '').lower() in denied) else sqlite3.SQLITE_DENY)
            con.execute('EXPLAIN QUERY PLAN '+executable_sql(sql,schema)).fetchall()
        return True,None
    except (sqlite3.Error,ValueError,TypeError) as exc:
        return False,str(exc)


def parse_structural(sql, schema):
    if not isinstance(sql, str) or not sql.strip() or len(sql) > 20000:
        raise ValueError('Empty or overlong SQL')
    valid,error=compile_readonly_sql(sql,schema)
    if not valid:
        raise ValueError('SQLite schema compilation failed: '+str(error))
    names = _identifiers(schema)
    mapped = {names[t.casefold()]: [names[c['name'].casefold()] for c in info['columns']]
              for t, info in schema.items()}
    parsed_schema = parser.Schema(mapped)
    query = _rewrite(sql, schema)
    # Normalize whitespace around qualification and explicit aliases. Implicit
    # table aliases are rewritten into the AS form required by upstream.
    query = re.sub(r'\s*\.\s*', '.', query)
    query = re.sub(r'\b(from|join)\s+(u\d+)\s+(?!as\b|where\b|join\b|on\b|group\b|order\b|limit\b|union\b|except\b|intersect\b)([a-zA-Z_]\w*)\b', r'\1 \2 as \3', query, flags=re.I)
    result = parser.get_sql(parsed_schema, query)
    kmap = {}
    # Transitive FK equivalence, consistent with Spider's official policy.
    groups = []
    for table, info in schema.items():
        for fk in info.get('foreign_keys', []):
            a = parsed_schema.idMap[names[table.casefold()] + '.' + names[fk['from'].casefold()]]
            b = parsed_schema.idMap[names[fk['table'].casefold()] + '.' + names[fk['to'].casefold()]]
            merged = {a, b}
            matches = [g for g in groups if g & merged]
            for g in matches:
                merged.update(g)
                groups.remove(g)
            groups.append(merged)
    for group in groups:
        kmap.update({key: min(group) for key in group})
    valid = spider.build_valid_col_units(result['from']['table_units'], parsed_schema)
    normalized = spider.rebuild_sql_col(valid, spider.rebuild_sql_val(result), kmap)
    return normalized


def execute_full_readonly(path, sql, timeout_s=5, max_rows=100000, max_bytes=16 * 1024 * 1024):
    """Fetch all rows or fail coverage; partial rows are never correctness data."""
    started = time.perf_counter()
    result = {'status': 'error', 'rows': [], 'columns': [], 'complete': False,
              'truncated': False, 'error': None, 'duration_ms': 0}
    if not isinstance(sql, str) or not sql.strip() or len(sql) > 20000:
        result['error'] = 'Empty or overlong SQL'
        return result
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
    denied_functions = {'load_extension', 'readfile', 'writefile', 'eval', 'randomblob', 'zeroblob', 'printf', 'format'}
    def authorize(action, a, b, db, source):
        return sqlite3.SQLITE_OK if action in allowed and not (action == sqlite3.SQLITE_FUNCTION and (b or '').lower() in denied_functions) else sqlite3.SQLITE_DENY
    try:
        assert_frozen_database(path)
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as con:
            con.execute('PRAGMA query_only=ON')
            con.enable_load_extension(False)
            if hasattr(con, 'setlimit'):
                con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1024 * 1024)
                con.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 20000)
            con.set_authorizer(authorize)
            con.set_progress_handler(lambda: int(time.perf_counter() - started > timeout_s), 1000)
            cursor = con.execute(sql)
            result['columns'] = [c[0] for c in cursor.description or []]
            used = 0
            for row in cursor:
                used += sum(len(v) if isinstance(v, (str, bytes)) else 16 for v in row)
                if len(result['rows']) >= max_rows or used > max_bytes or time.perf_counter() - started > timeout_s:
                    result.update(status='bounded', truncated=True, error='Complete result exceeded row/byte/time bound')
                    break
                result['rows'].append(list(row))
            else:
                result.update(status='ok', complete=True)
    except (sqlite3.Error, sqlite3.Warning, OSError, ValueError) as exc:
        result.update(status='timeout' if 'interrupted' in str(exc) else 'error', error=str(exc))
    result['duration_ms'] = round((time.perf_counter() - started) * 1000, 3)
    return result


def _audit_database(path, schema, sample, store, timeout_s):
    try:
        assert_frozen_database(path)
    except (ValueError,OSError) as exc:
        return False,str(exc)
    stat = Path(path).stat()
    golds = [sample]
    if hasattr(store, 'samples_for_database'):
        golds = store.samples_for_database(sample['db_id'])
    elif hasattr(store, 'samples'):
        golds = [s for split in ('train', 'dev', 'test') for s in store.samples(split) if s['db_id'] == sample['db_id']]
    key = (str(Path(path).resolve()), stat.st_size, stat.st_mtime_ns,hashlib.sha256(Path(path).read_bytes()).hexdigest(),
           hashlib.sha256(json.dumps([schema, [s.get('gold_sql') for s in golds]], sort_keys=True).encode()).hexdigest())
    if key in _AUDITS:
        return _AUDITS[key]
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as con:
            total_nonempty = False
            for name, info in schema.items():
                actual = {r[1].casefold() for r in con.execute('PRAGMA table_info(' + quote_identifier(name) + ')')}
                expected = {c['name'].casefold() for c in info['columns']}
                if actual != expected:
                    raise ValueError('SQLite schema incompatible with Vietnamese identifiers: ' + name)
                if con.execute('SELECT 1 FROM ' + quote_identifier(name) + ' LIMIT 1').fetchone():
                    total_nonempty = True
            if not total_nonempty:
                raise ValueError('Database has no data; synthetic empty schemas cannot qualify for EX')
        for gold in golds:
            if not gold.get('gold_sql'):
                continue
            result = execute_full_readonly(path, executable_sql(gold['gold_sql'], schema), timeout_s)
            if not result['complete']:
                raise ValueError('Gold SQL execution audit failed: ' + str(result['error']))
        answer = (True, None)
    except (sqlite3.Error, OSError, ValueError) as exc:
        answer = (False, str(exc))
    _AUDITS[key] = answer
    return answer


def _state_fingerprint(path, schema, timeout_s):
    assert_frozen_database(path)
    stat = Path(path).stat()
    key = (str(Path(path).resolve()), stat.st_size, stat.st_mtime_ns, hashlib.sha256(Path(path).read_bytes()).hexdigest(), json.dumps(schema, sort_keys=True))
    if key not in _STATE_FINGERPRINTS:
        digest = hashlib.sha256()
        for name in sorted(schema):
            rows = execute_full_readonly(path, 'SELECT * FROM ' + quote_identifier(name), timeout_s)
            if not rows['complete']:
                raise ValueError('Test-suite complete data-state audit failed: ' + str(rows['error']))
            # Ignore storage layout and physical row order, preserve duplicates.
            canonical = sorted(repr(tuple((type(v).__name__, v) for v in row)) for row in rows['rows'])
            digest.update(repr((name, canonical)).encode('utf-8'))
        _STATE_FINGERPRINTS[key] = digest.hexdigest()
    return _STATE_FINGERPRINTS[key]


def top_level_ordered(sql):
    # Strings, quoted identifiers and comments cannot impose result ordering.
    pattern=r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[[^\]]*\]|--[^\n]*|/\*.*?\*/|[()]|[\w]+"
    depth=0; previous=None
    for token in re.findall(pattern,sql or '',re.S):
        if token.startswith(("'",'"','`','[','--','/*')):
            continue
        if token=='(':
            depth+=1; previous=None; continue
        if token==')':
            depth=max(0,depth-1); previous=None; continue
        if depth==0:
            word=token.casefold()
            if previous=='order' and word=='by':
                return True
            previous=word
    return False


def _rows_match(predicted, expected, ordered):
    if len(predicted)!=len(expected):
        return False
    if not expected:
        return True
    width=len(expected[0])
    if any(len(row)!=width for row in predicted+expected):
        return False
    exact=predicted==expected if ordered else Counter(map(tuple,predicted))==Counter(map(tuple,expected))
    if exact:
        return True
    candidates=[]
    for i in range(width):
        target=[row[i] for row in expected]
        choices=[]
        for j in range(width):
            values=[row[j] for row in predicted]
            if (values==target if ordered else Counter(values)==Counter(target)):
                choices.append(j)
        if not choices:
            return False
        candidates.append(choices)
    # One column permutation must work for the entire result, not per-row sorts.
    visited=0
    def align(mapping,used):
        nonlocal visited
        visited+=1
        if visited>4096:
            return False
        if len(mapping)==width:
            return True
        for column in candidates[len(mapping)]:
            if column in used:
                continue
            proposal=mapping+[column]
            left=[tuple(row[c] for c in proposal) for row in predicted]
            right=[tuple(row[:len(proposal)]) for row in expected]
            if (left==right if ordered else Counter(left)==Counter(right)) and align(proposal,used|{column}):
                return True
        return False
    return align([],set())


def _results_match(predicted,expected,ordered):
    return len(predicted['columns'])==len(expected['columns']) and _rows_match(predicted['rows'],expected['rows'],ordered)


def _test_suite_score(sql, sample, store, schema, timeout_s):
    details = {'validated_states': 0, 'evaluated_states': 0, 'policy': 'local_adapted_test_suite_v1'}
    if not sample.get('gold_sql'):
        return None, details, 'No gold SQL for this free-form question.'
    if not hasattr(store, 'test_suite_assets'):
        return None, details, 'Validated test-suite manifest unavailable.'
    try:
        assets = store.test_suite_assets(sample['db_id'])
        if not assets['available']:
            return None, details, assets['reason']
        files = assets['files']
        states = set()
        for entry in files:
            valid, reason = _audit_database(entry['path'], schema, sample, store, timeout_s)
            if not valid:
                return None, details, 'Test-suite schema/data/gold audit failed: ' + str(reason)
            states.add(_state_fingerprint(entry['path'], schema, timeout_s))
            details['validated_states'] += 1
        if len(states) < 2:
            return None, details, 'Test-suite assets contain fewer than two distinct data states.'
        ordered = top_level_ordered(sample['gold_sql'])
        correct = True
        for entry in files:
            expected = execute_full_readonly(entry['path'], executable_sql(sample['gold_sql'], schema), timeout_s)
            predicted = execute_full_readonly(entry['path'], executable_sql(sql, schema), timeout_s)
            if not expected['complete']:
                return None, details, 'Test-suite target gold complete execution unavailable: ' + str(expected['error'])
            details['evaluated_states'] += 1
            correct = correct and predicted['complete'] and _results_match(predicted,expected,ordered)
        return int(correct), details, None
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        return None, details, 'Test-suite validation unavailable: ' + str(exc)


def _ves_score(sql, sample, store, schema, timeout_s, result):
    details = {'completed_pairs': 0, 'sql_executions': 0, 'policy': 'local_adapted_ves_v1',
               'statistic': 'mean(sqrt(gold_sql_ms / predicted_sql_ms))',
               'timing_scope': 'Complete read-only SQLite execution including connection and fetching'}
    options = store.evaluation_options() if hasattr(store, 'evaluation_options') else {}
    repeats = options.get('ves_repeats')
    if options.get('ves_enabled') is False:
        return None, details, 'VES explicitly disabled in evaluation-options.json.'
    if options.get('error'):
        return None, details, 'Invalid evaluation-options.json: ' + options['error']
    if not isinstance(repeats, int) or isinstance(repeats, bool) or not 100 <= repeats <= 1000:
        return None, details, 'Explicit evaluation-options.json ves_repeats between 100 and 1000 required.'
    details['requested_pairs'] = repeats
    if result.get('ex') is None or result.get('gold_valid') is not True:
        return None, details, 'VES requires compatible data-filled SQLite, successful gold audit and available EX.'
    if result['ex'] == 0:
        return 0.0, details, None
    path = store.database_path(sample['db_id'])
    budget = options.get('ves_budget_s', 60)
    if not isinstance(budget, (int, float)) or isinstance(budget, bool) or not 0 < budget <= 600:
        return None, details, 'VES total timing budget must be positive and at most 600 seconds.'
    ratios = []
    gold_times = []
    predicted_times = []
    started = time.perf_counter()
    gold_sql = executable_sql(sample['gold_sql'], schema)
    predicted_sql = executable_sql(sql, schema)
    ordered = top_level_ordered(sample['gold_sql'])
    for index in range(repeats):
        if time.perf_counter() - started >= budget:
            return None, details, 'VES repetition budget expired before all requested pairs completed.'
        pair = {}
        # Interleave paired runs and alternate which query runs first to reduce
        # systematic warm-cache ordering bias. This is local wall-clock VES.
        order = ('gold', 'prediction') if index % 2 == 0 else ('prediction', 'gold')
        for role in order:
            remaining = budget - (time.perf_counter() - started)
            if remaining <= 0:
                return None, details, 'VES repetition budget expired before all requested pairs completed.'
            query = gold_sql if role == 'gold' else predicted_sql
            pair[role] = execute_full_readonly(path, query, min(timeout_s, remaining))
            details['sql_executions'] += 1
        if not all(value['complete'] for value in pair.values()):
            return None, details, 'VES repeated full execution failed or exceeded a bound.'
        if not _results_match(pair['prediction'],pair['gold'],ordered):
            return None, details, 'VES repeated result changed; stable correct execution required.'
        gold_ms = pair['gold']['duration_ms']
        prediction_ms = pair['prediction']['duration_ms']
        if gold_ms <= 0 or prediction_ms <= 0:
            return None, details, 'VES timings below clock resolution.'
        ratios.append(math.sqrt(gold_ms / prediction_ms))
        gold_times.append(gold_ms)
        predicted_times.append(prediction_ms)
        details['completed_pairs'] += 1
    details['gold_mean_sql_ms'] = sum(gold_times) / repeats
    details['prediction_mean_sql_ms'] = sum(predicted_times) / repeats
    return sum(ratios) / repeats, details, None


def _optional_metrics(result, sql, sample, store, schema, timeout_s):
    ts, ts_details, ts_reason = _test_suite_score(sql, sample, store, schema, timeout_s)
    result.update(ts=ts, ts_details=ts_details)
    if ts_reason:
        result['unavailable_reasons']['ts'] = ts_reason
    else:
        result['unavailable_reasons'].pop('ts', None)
    ves, ves_details, ves_reason = _ves_score(sql, sample, store, schema, timeout_s, result)
    result.update(ves=ves, ves_details=ves_details)
    if ves_reason:
        result['unavailable_reasons']['ves'] = ves_reason
    else:
        result['unavailable_reasons'].pop('ves', None)
    # Recheck frozen assets after execution so a writer cannot change the state
    # between the preflight snapshot and publication of its score.
    if result.get('ex') is not None:
        try:
            store.database_path(sample['db_id'])
        except (ValueError,OSError) as exc:
            result.update(ex=None,ves=None)
            result['unavailable_reasons']['ex']=str(exc)
            result['unavailable_reasons']['ves']='Database snapshot changed during evaluation.'
    if result.get('ts') is not None and hasattr(store,'test_suite_assets'):
        try:
            assets=store.test_suite_assets(sample['db_id'])
            if not assets['available']:
                result['ts']=None
                result['unavailable_reasons']['ts']=assets['reason']
        except (ValueError,OSError) as exc:
            result['ts']=None
            result['unavailable_reasons']['ts']=str(exc)
    return result


def evaluate_prediction(sql, sample, store, timeout_s=5):
    result = {k: None for k in ('em', 'cm', 'ex', 'ts', 'ves', 'syntax_valid', 'execution_success', 'sql_latency_ms', 'gold_valid')}
    result['cm_components'] = {}
    reasons = result['unavailable_reasons'] = {
        'ts': 'Validated test-suite databases and test-suite execution assets unavailable.',
        'ves': 'Validated efficiency measurement assets and repeated performance protocol unavailable.'}
    schema = store.schema(sample['db_id'])
    predicted = gold = None
    result['syntax_valid'],syntax_error=compile_readonly_sql(sql,schema)
    try:
        predicted = parse_structural(sql, schema)
    except (AssertionError, ValueError, KeyError, IndexError, TypeError, RecursionError) as exc:
        reasons['structural_prediction'] = 'Spider adapter cannot parse prediction: ' + str(exc)
    if sample.get('gold_sql'):
        try:
            gold = parse_structural(sample['gold_sql'], schema)
            result['gold_valid'] = True
        except (AssertionError, ValueError, KeyError, IndexError, TypeError, RecursionError) as exc:
            result['gold_valid'] = False
            reasons['em'] = reasons['cm'] = 'Gold SQL unsupported by Spider adapter: ' + str(exc)
        if gold is not None:
            if predicted is None:
                result.update(em=0, cm=0)
            else:
                evaluator = spider.Evaluator()
                result['em'] = evaluator.eval_exact_match(copy.deepcopy(predicted), copy.deepcopy(gold))
                components = evaluator.partial_scores
                result['cm_components'] = components
                active = [v['f1'] for v in components.values() if v['label_total'] or v['pred_total']]
                result['cm'] = sum(active) / len(active) if active else 1.0
    else:
        reasons['em'] = reasons['cm'] = 'No gold SQL for this free-form question.'
    try:
        path = store.database_path(sample['db_id'])
    except (ValueError,OSError) as exc:
        reasons['ex']=str(exc)
        return _optional_metrics(result,sql,sample,store,schema,timeout_s)
    if path is None:
        reasons['ex'] = 'Compatible data-filled SQLite database unavailable.'
        return _optional_metrics(result, sql, sample, store, schema, timeout_s)
    qualified, reason = _audit_database(path, schema, sample, store, timeout_s)
    if not qualified:
        reasons['ex'] = reason
        return _optional_metrics(result, sql, sample, store, schema, timeout_s)
    execution = execute_full_readonly(path, executable_sql(sql, schema), timeout_s)
    result['execution_success'] = execution['complete']
    result['sql_latency_ms'] = execution['duration_ms']
    if not sample.get('gold_sql'):
        reasons['ex'] = 'No gold SQL for this free-form question.'
        return _optional_metrics(result, sql, sample, store, schema, timeout_s)
    expected = execute_full_readonly(path, executable_sql(sample['gold_sql'], schema), timeout_s)
    result['gold_valid'] = expected['complete']
    if not expected['complete']:
        reasons['ex'] = 'Gold full execution unavailable: ' + str(expected['error'])
    elif execution['status'] in ('bounded', 'timeout'):
        result['ex'] = 0
        reasons['execution_error'] = 'Prediction exceeded the fixed execution resource bound: ' + str(execution['error'])
    elif not execution['complete']:
        result['ex'] = 0
    else:
        result['ex'] = int(_results_match(execution,expected,top_level_ordered(sample['gold_sql'])))
    return _optional_metrics(result, sql, sample, store, schema, timeout_s)
