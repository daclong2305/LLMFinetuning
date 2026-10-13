"""Create the synthetic architecture SQLite database for the ViSQL demo."""
import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def seed_database(database_dir):
    database_dir = Path(database_dir)
    path = database_dir / 'architecture' / 'architecture.sqlite'
    if (database_dir / 'architecture.sqlite').exists():
        raise FileExistsError('An architecture database already exists in the flat layout')
    path.parent.mkdir(parents=True, exist_ok=True)
    # Reserve exclusively: never replace a real database or a user's edits.
    with path.open('xb'):
        pass
    try:
        with closing(sqlite3.connect(path)) as con:
            con.executescript((ROOT / 'data' / 'architecture-demo.sql').read_text(encoding='utf-8'))
            if con.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Seed data violates foreign keys')
            if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('SQLite integrity check failed')
    except Exception:
        path.unlink()
        raise
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-dir', type=Path, help='Override the configured SQLite directory')
    args = parser.parse_args()
    from text2sql_demo.experiment.service import load_config
    directory = args.database_dir or Path(load_config(ROOT)['database_dir'])
    try:
        path = seed_database(directory)
    except FileExistsError:
        parser.exit(1, 'Database already exists; kept unchanged. Use --database-dir for a separate demo copy.\n')
    print(json.dumps({'db_id': 'architecture', 'path': str(path.resolve()), 'synthetic': True,
                      'rows': {'architects': 8, 'bridges': 12, 'mills': 10},
                      'next': 'Restart ViSQL, select Dev / architecture, then run a question.'}, indent=2))


if __name__ == '__main__':
    main()
