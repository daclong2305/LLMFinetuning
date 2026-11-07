"""Download pinned public execution assets privately; no dependency installation.

Usage: python scripts/download_execution_sources.py [--output DIRECTORY]
Google Drive quota failures may fall back to the pinned, checksummed Spider
mirror. The manifest always records the actual acquisition URL.
"""
import argparse
import hashlib
import html
import http.cookiejar
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPIDER_ORIGIN = 'https://drive.google.com/uc?export=download&id=1403EGqzIDoHMdQF4c9Bkyl7dZLZ5Wt6J'
SOURCES = {
    'spider_data.zip': {
        'sha256': '00636695dabed6b5f4b8328a16b13e069a2f16591d5efcce57660669c85b121b',
        'urls': [SPIDER_ORIGIN, 'https://huggingface.co/datasets/HAL-9001/spider-databases/resolve/4a01bbac6520cd35b216db9e1724e5e1ada60aa4/spider_data.zip']},
    'testsuitedatabases.zip': {
        'sha256': '9ec24ea8debc6bd04abfe137b5f1a739b5a8836f32c0464e4dfc94eb7f41da96',
        'urls': ['https://drive.google.com/uc?export=download&id=1mkCx2GOFIqNesD4y8TDAO1yX1QZORP5w']},
    'suite-tables.json': {
        'sha256': 'b68de9166952871d64554486fca4b25ff88509e983857a6af428250ffd58b67f',
        'urls': ['https://raw.githubusercontent.com/taoyds/test-suite-sql-eval/e97acc546ecbee8fa27fa8dbf025ef61493a876c/tables.json']},
}


def stream_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(dest, urls, expected_sha256):
    dest = Path(dest)
    if dest.exists():
        if stream_hash(dest) != expected_sha256:
            raise ValueError('Cached source checksum mismatch; file preserved: ' + str(dest))
        lock_path = dest.with_name(dest.name + '.source.json')
        if not lock_path.is_file():
            raise ValueError('Cached source lacks acquisition provenance: ' + str(dest))
        lock = json.loads(lock_path.read_text(encoding='utf-8'))
        if lock.get('sha256') != expected_sha256:
            raise ValueError('Acquisition provenance hash mismatch')
        return lock
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + '.part')
    errors = []
    for url in urls:
        response = None
        try:
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            response = opener.open(url, timeout=120)
            if 'text/html' in response.headers.get('Content-Type', ''):
                page = response.read(128 * 1024).decode('utf-8')
                response.close()
                fields = {html.unescape(k): html.unescape(v) for k, v in re.findall(r'name="([^"]+)" value="([^"]*)"', page)
                          if k in ('id', 'export', 'confirm', 'uuid')}
                original_id = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get('id', [None])[0]
                if not original_id or fields.get('id') != original_id or not fields.get('uuid'):
                    raise ValueError('Source returned HTML/quota page instead of file')
                response = opener.open('https://drive.usercontent.google.com/download?' + urllib.parse.urlencode(fields), timeout=120)
                if 'text/html' in response.headers.get('Content-Type', ''):
                    raise ValueError('Confirmed download returned HTML/quota page')
            digest, total, last = hashlib.sha256(), 0, time.monotonic()
            with partial.open('wb') as output:
                while chunk := response.read(4 * 1024 * 1024):
                    total += len(chunk)
                    if total > 2 * 1024 ** 3:
                        raise ValueError('Download exceeds 2 GiB bound')
                    output.write(chunk)
                    digest.update(chunk)
                    if time.monotonic() - last > 10:
                        print(dest.name, total // 1048576, 'MiB', flush=True)
                        last = time.monotonic()
            if digest.hexdigest() != expected_sha256:
                raise ValueError('Downloaded source checksum mismatch')
            partial.rename(dest)
            record = {'url': url, 'official_origin': urls[0], 'sha256': expected_sha256,
                      'size': total, 'fallback_reasons': errors}
            dest.with_name(dest.name + '.source.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
            return record
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
        finally:
            if response is not None:
                response.close()
            partial.unlink(missing_ok=True)
    raise ValueError('No pinned source could be acquired: ' + '; '.join(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.runtime/metric-sources')
    args = parser.parse_args()
    for name, source in SOURCES.items():
        record = download_file(args.output / name, source['urls'], source['sha256'])
        print(name, record['size'], record['sha256'], flush=True)


if __name__ == '__main__':
    main()
