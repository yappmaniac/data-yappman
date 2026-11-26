"""GB driving-test waits: fetch the four public DVSA ODS files from gov.uk. No credential, no login.

    python -I -B docs/release/fetch_driving_test_waits.py --dry-run   # ONE request: resolves the file URLs; saves nothing
    python -I -B docs/release/fetch_driving_test_waits.py --status    # ONE request: has DVSA published something newer than what we published?
    python -I -B docs/release/fetch_driving_test_waits.py --fetch     # the four files, once each, into _incoming/driving-test/

then the build (no network): python -I -B docs/release/driving_test_waits_site.py --describe | --check | --publish

STATUS (26 Nov 2026): tested on fake responses. Run once for real by the Orchestrator on 26 Nov 2026 at 18:55 UTC (one
--dry-run, then one --fetch: 5 requests), after Russell's typed yes in the Orchestrator chat for the four files (about 4.5 MB,
public, OGL). Downloading stays a gated act: each later monthly fetch is covered only by a go that says so.

Rules (modelled on fetch_authority_yield.py, minus the token):
- the only start is the content API  https://www.gov.uk/api/content/government/statistical-data-sets/driving-test-and-theory-test-data-cars
  (keyless; the asset ids change with each upload, so the URLs are read from it each time). Shape (it worked on the real run of
  26 Nov 2026): the JSON holds, somewhere, objects with a "url" ending .ods on assets.publishing.service.gov.uk and a "title" or
  file name containing the table code; the tool finds them by walking the JSON and refuses an ambiguous or missing table.
  `public_updated_at` is the gov.uk PAGE's last-updated time (any change to the page moves it, so it is shown on our page as
  "gov.uk page last updated", not as the date of the files; the DRT122F cover sheet carries its own date);
- hosts: only www.gov.uk and assets.publishing.service.gov.uk, HTTPS with a verified TLS context (1.2 or later, no key
  log, refused when SSL_CERT_FILE and friends are set), no proxy, NO redirect followed (a 3xx stops the run), a timeout,
  a size cap, a pause between requests, no query string or fragment in any URL;
- each file is requested ONCE; at most one more try after a 429 or 5xx; no retry on a 4xx or a network failure; any block
  or 4xx stops the whole run, nothing saved. A reply that is not a readable zip with a content.xml is refused;
- --fetch saves to the git-ignored _incoming/driving-test/ (folders starting with _ are not served), each file written as
  <name>.part opened with O_EXCL then moved into place, FACTS.json last (names, sizes, SHA-256, the release and last-updated
  dates, the read time). The folder and files must not be links; a leftover .part stops the run (exit 5);
- prints one JSON line of facts. No URL, no response body.

Exit codes: 0 done; 2 refused (nothing requested); 3 the API answered but the files could not be identified (nothing saved);
4 a request failed (nothing saved); 5 a .part file is left over.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dvsa_ods  # noqa: E402
import fetch_authority_yield as fay  # noqa: E402  (its reviewed TLS context and no-redirect opener; nothing else is used)

API_URL = 'https://www.gov.uk/api/content/government/statistical-data-sets/driving-test-and-theory-test-data-cars'
TABLES = ('DRT122F', 'DRT121G', 'DRT121A', 'DRT121B')
REPO = Path(__file__).resolve().parents[2]
INCOMING = Path('_incoming/driving-test')
FACTS_FILE = 'FACTS.json'
ALLOWED_HOSTS = ('www.gov.uk', 'assets.publishing.service.gov.uk')
ASSET_RE = re.compile(r'https://assets\.publishing\.service\.gov\.uk/media/[0-9a-f]{24}/[A-Za-z0-9._()-]{1,120}\.ods')
CODE_RE = re.compile(r'DRT12[12][A-G]', re.IGNORECASE)
TIMEOUT_SECONDS = 90
PACE_SECONDS = 1.0
MAX_ATTEMPTS = 2                 # one try and at most one more after a 429 or 5xx
BACKOFF_SECONDS = 5.0
MAX_API_BYTES = 4_000_000
MAX_FILE_BYTES = 15_000_000      # the biggest of the four is about 4.1 MB
LEFTOVER_EXIT = 5
USER_AGENT = 'yappman-data-driving-test-waits/1'


class FetchError(Exception):
    def __init__(self, code: str, status: int | None = None, *, exit_code: int = 4) -> None:
        super().__init__(code)
        self.code, self.status, self.exit_code = code, status, exit_code


def refused(code: str) -> FetchError:
    return FetchError(code, exit_code=2)


def emit(line: str) -> None:
    print(line)


class Transport:
    """GET only, to the API URL or an asset URL found in it. `opener` and `sleep` are for the tests only."""

    def __init__(self, *, opener: Any = None, sleep: Callable[[float], None] = time.sleep) -> None:
        self._opener, self._sleep = opener, sleep
        self._last: float | None = None
        self.requests = 0

    def _once(self, url: str, limit: int) -> tuple[int, bytes]:
        if self._last is not None and time.monotonic() - self._last < PACE_SECONDS:
            self._sleep(PACE_SECONDS)
        self._last = time.monotonic()
        if not (url == API_URL or ASSET_RE.fullmatch(url)) or any(c in url for c in '?#%\\') or '..' in url:
            raise refused('url-refused')
        request = urllib.request.Request(url, headers={'Accept': '*/*', 'User-Agent': USER_AGENT}, method='GET')
        self.requests += 1
        try:
            with (self._opener or fay.build_opener()).open(request, timeout=TIMEOUT_SECONDS) as reply:
                status = int(reply.status)
                data = reply.read(limit + 1)
        except urllib.error.HTTPError as error:
            status = int(error.code)
            error.close()
            if 300 <= status < 400:
                raise FetchError('redirect-refused', status) from None
            return status, b''
        except Exception:  # noqa: BLE001 - the type, URL and message are dropped
            raise FetchError('network-failure') from None
        if 300 <= status < 400:
            raise FetchError('redirect-refused', status)
        if len(data) > limit:
            raise FetchError('response-too-large', status)
        return status, data

    def get(self, url: str, limit: int) -> bytes:
        for attempt in range(MAX_ATTEMPTS):
            status, body = self._once(url, limit)
            if status == 200:
                return body
            if status != 429 and status < 500:
                raise FetchError('blocked-or-not-found' if status in (401, 403, 404) else 'unexpected-status', status)
            if attempt + 1 < MAX_ATTEMPTS:
                self._sleep(BACKOFF_SECONDS)
        raise FetchError('retries-exhausted', status)


# ------------------------------------------------------------------------------ resolving the files

def _walk(node: Any, depth: int = 0) -> Any:
    if depth > 40:
        raise FetchError('api-too-deep', exit_code=3)
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value, depth + 1)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value, depth + 1)


def second_wednesday(year: int, month: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(2 - first.weekday()) % 7 + 7)


def release_date_for(updated: date) -> date:
    """ASSUMED: DVSA updates only on or after the monthly release, so the release is the latest second Wednesday that is
    not after the last-updated date (13 Nov fix -> 11 Nov release)."""
    this_month = second_wednesday(updated.year, updated.month)
    if this_month <= updated:
        return this_month
    year, month = (updated.year - 1, 12) if updated.month == 1 else (updated.year, updated.month - 1)
    return second_wednesday(year, month)


def resolve(api_body: bytes) -> dict[str, Any]:
    """{'urls': {table: url}, 'lastUpdated': 'YYYY-MM-DD', 'releaseDate': 'YYYY-MM-DD'} from the content API's JSON."""
    try:
        document = json.loads(api_body.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise FetchError('api-not-json', exit_code=3) from None
    found: dict[str, set[str]] = {}
    for node in _walk(document):
        if not isinstance(node, dict):
            continue
        url = node.get('url')
        if not (isinstance(url, str) and ASSET_RE.fullmatch(url)):
            continue
        label = ' '.join(str(node.get(k, '')) for k in ('title', 'filename', 'file_name')) + ' ' + url
        for code in {c.upper() for c in CODE_RE.findall(label)}:
            if code in TABLES:
                found.setdefault(code, set()).add(url)
    for table in TABLES:
        if len(found.get(table, ())) != 1:
            raise FetchError(f'table-not-found-once-{table}', exit_code=3)
    updated = document.get('public_updated_at') if isinstance(document, dict) else None
    if not (isinstance(updated, str) and re.fullmatch(r'20[0-9]{2}-[0-9]{2}-[0-9]{2}T.*', updated)):
        raise FetchError('last-updated-not-found', exit_code=3)
    try:
        last = date.fromisoformat(updated[:10])
    except ValueError:
        raise FetchError('last-updated-not-a-date', exit_code=3) from None
    return {'urls': {t: next(iter(found[t])) for t in TABLES}, 'lastUpdated': last.isoformat(),
            'releaseDate': release_date_for(last).isoformat()}


# ------------------------------------------------------------------------------ the run

def _is_link(path: Path) -> bool:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, 'st_file_attributes', 0) & reparse)


def refuse_links(root: Path, *relatives: Path) -> None:
    for relative in relatives:
        current = root
        for part in relative.parts:
            current = current / part
            if _is_link(current):
                raise FetchError('link-refused', exit_code=2)


def check_incoming(root: Path) -> None:
    names = [f'{t}.ods' for t in TABLES] + [FACTS_FILE]
    refuse_links(root, INCOMING, *(INCOMING / n for n in names))
    if any((root / INCOMING / (n + '.part')).exists() for n in names):
        raise FetchError('part-file-left-over', exit_code=LEFTOVER_EXIT)


def _write(root: Path, name: str, data: bytes) -> None:
    target = root / INCOMING / name
    temporary = target.with_name(name + '.part')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o644)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, target)


def status(root: Path, resolved: dict[str, Any], requests: int) -> dict[str, Any]:
    """Compare DVSA's release and last-updated dates with the published latest file (read only; nothing is saved)."""
    facts = {'dvsaReleaseDate': resolved['releaseDate'], 'dvsaLastUpdated': resolved['lastUpdated'], 'requests': requests}
    latest = root / 'data/driving-test-waits/driving-test-waits-latest.json'
    if not latest.exists():
        return {'status': 'nothing-published', **facts}
    try:
        document = json.loads(latest.read_bytes().decode('utf-8'))
        ours = {'ourMonth': document['month'], 'ourVintage': document['vintage'], 'ourLastUpdated': document['lastUpdated']}
        if not all(isinstance(v, str) for v in ours.values()):
            raise ValueError
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        raise FetchError('published-file-unreadable', exit_code=3) from None
    if resolved['releaseDate'] > ours['ourVintage']:
        state = 'newer-release'
    elif resolved['lastUpdated'] > ours['ourLastUpdated']:
        state = 'updated-since'
    else:
        state = 'up-to-date'
    return {'status': state, **ours, **facts}


def run(args: argparse.Namespace, transport: Transport, root: Path, now: datetime) -> dict[str, Any]:
    resolved = resolve(transport.get(API_URL, MAX_API_BYTES))
    if args.status:
        return status(root, resolved, transport.requests)
    if args.dry_run:
        return {'status': 'dry-run', 'tables': list(TABLES), 'lastUpdated': resolved['lastUpdated'],
                'releaseDate': resolved['releaseDate'], 'requests': transport.requests}
    files: dict[str, bytes] = {}
    for table in TABLES:
        body = transport.get(resolved['urls'][table], MAX_FILE_BYTES)
        try:
            dvsa_ods._open_content(body)                 # a zip with one readable content.xml, or an OdsError
        except dvsa_ods.OdsError:
            raise FetchError('not-a-readable-ods', exit_code=3) from None
        files[table] = body
    check_incoming(root)
    (root / INCOMING).mkdir(parents=True, exist_ok=True)
    check_incoming(root)
    for table, body in files.items():
        _write(root, f'{table}.ods', body)
    facts = {'v': 1, 'releaseDate': resolved['releaseDate'], 'lastUpdated': resolved['lastUpdated'],
             'readAt': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
             'files': {t: {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()} for t, b in files.items()}}
    _write(root, FACTS_FILE, (json.dumps(facts, indent=1) + '\n').encode('utf-8'))
    return {'status': 'fetched', **{k: facts[k] for k in ('releaseDate', 'lastUpdated', 'readAt')},
            'files': facts['files'], 'folder': str(INCOMING), 'requests': transport.requests}


def is_this_repo(root: Path) -> bool:
    try:
        return (root / 'CNAME').read_text(encoding='utf-8').strip() == 'data.yappman.com'
    except OSError:
        return False


def main(argv: list[str] | None = None, *, opener: Any = None, root: Path = REPO,
         sleep: Callable[[float], None] = time.sleep, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true', help='one request to the content API; prints what it found')
    mode.add_argument('--status', action='store_true', help='one request to the content API; compares with what is published')
    mode.add_argument('--fetch', action='store_true', help='the four files, once each, into _incoming/driving-test/')
    args = parser.parse_args(argv)
    real = opener is None
    if real and not sys.flags.isolated:
        emit(json.dumps({'status': 'refused', 'code': 'run-with-python-I'}))
        return 2
    if real and any(os.environ.get(n) for n in fay.TLS_OVERRIDES):
        emit(json.dumps({'status': 'refused', 'code': 'tls-override-set'}))
        return 2
    if not is_this_repo(root):
        emit(json.dumps({'status': 'refused', 'code': 'not-the-data-yappman-repo'}))
        return 2
    try:
        if args.fetch:
            check_incoming(root)
        result = run(args, Transport(opener=opener, sleep=sleep), root, now or datetime.now(UTC))
    except FetchError as error:
        line = {'status': 'refused' if error.exit_code == 2 else 'stopped', 'code': error.code, 'httpStatus': error.status}
        if error.exit_code == LEFTOVER_EXIT:
            line['hint'] = 'a .part file is left over in _incoming/driving-test: check it, delete it by hand, then run again'
        emit(json.dumps(line))
        return error.exit_code
    except Exception as error:  # noqa: BLE001 - the type only
        emit(json.dumps({'status': 'failed', 'type': type(error).__name__}))
        return 4
    emit(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
