"""Median sold prices by local authority and region, yearly and quarterly (area history): fetch the files from the
Property session's Apify store.

RUSSELL RUNS THIS, in his own terminal, with `python -I` (it refuses without it). It refuses to run inside a Claude
Code session (CLAUDECODE set), and no session reads, lists or prints the credential it uses. The CLAUDECODE check is a
guard against mistakes, not a security boundary: the token's own scope (read-only, this one store) is what limits it.

    python -I -B docs/release/fetch_area_history.py --dry-run   # reads AH_STATE only; prints its facts; saves nothing
    python -I -B docs/release/fetch_area_history.py --fetch     # AH_STATE, ah_index.json, each listed file's two records

then the build, which needs no token and no network:

    python -I -B docs/release/area_history_site.py --check [--first-publish]
    python -I -B docs/release/area_history_site.py --publish [--first-publish]

A separate script on the pattern of fetch_district_history.py and fetch_authority_yield.py (those files and their keys
are unchanged); every line outside the changes below is the reviewed file's. What differs:
- The record keys. Only these can be requested: AH_STATE, ah_index.json, and for each base key the index lists
  (ah_regions, or ah_<REGION>_year, ah_<REGION>_qtr_1995-2009 and ah_<REGION>_qtr_2010-onwards where <REGION> is
  E12000001 to E12000009 or W92000004) its .json and its .csv record. The index is read first; a key it does not list
  is refused; at most 40 base keys. Every request is still a GET: this tool cannot write to the store, list its keys or
  read any other record. THE READ TOKEN MUST ALLOW THESE NEW KEYS: if it is limited to the district table's own named
  keys, extending it is Russell's own act (no session asks for or prints it).
- The request cap is computed from the index: 2 + 2 + 2 x (base keys) + 10 attempts of headroom (every attempt counts,
  retries included), at most 100; a request beyond it is refused and nothing is saved. Before the index is known the
  cap is 12.
- --fetch saves the files to _incoming/sold-prices-area-history/ in this repo (git-ignored, never published), only
  when AH_STATE and ah_index.json read again after the other records are unchanged; otherwise it saves nothing (a
  build was midway: try again later). Records are saved byte for byte. The credential, the TLS rules, the no-redirect
  rule, the output rules and the file rules (no links, .part opened with O_EXCL then moved into place) are those of
  fetch_authority_yield.py. The total of all records is limited to 150,000,000 bytes (about 90 MB expected).
- Output is one JSON line of facts: month, lastYear, lastQuarter, postcode release, builtAt, authority, region, file
  and row counts, the file count, the total and largest sizes, the SHA-256 of the state and of the index, and the
  folder name. No URL, key name list, body or token is printed.
- The files are written one by one after every check has passed. A failure partway through can leave a mix of new and
  old files; the folder must be cleared by hand before the next run (a leftover .part file or a file the index no
  longer lists is refused, exit 5 or 3).

Exit codes: 0 done; 2 refused (nothing read, or the request cap or a link refused after reading began: nothing saved);
3 the store answered but the history is not ready, or a check refused (nothing saved);
4 a request failed (nothing saved); 5 a .part file is left over from an earlier run (nothing read or saved: check it,
delete it by hand, run again).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import ssl
import stat
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BASE_URL = 'https://api.apify.com/v2'
STORE_URL = f'{BASE_URL}/key-value-stores/yappman~pp-district-table'
CREDENTIAL_TARGET = 'yappman/pp-district-read'
FIXED_KEYS = ('AH_STATE', 'ah_index.json')
BASE_KEY_RE = re.compile(r'ah_(?:regions|(?:E1200000[1-9]|W92000004)_(?:year|qtr_1995-2009|qtr_2010-onwards))')
RECORD_KEY_RE = re.compile(BASE_KEY_RE.pattern + r'\.(?:json|csv)')
MAX_BASES = 40
HARD_MAX_REQUESTS = 100
START_REQUESTS = 12     # AH_STATE and ah_index.json, with headroom, before the index is known
MAX_TOTAL_BYTES = 150_000_000   # all records together (about 90 MB expected); refused before anything is written
REPO = Path(__file__).resolve().parents[2]
INCOMING = Path('_incoming/sold-prices-area-history')
MONTH_RE = re.compile(r'[0-9]{4}-(?:0[1-9]|1[0-2])')                                         # as the build's
RELEASE_RE = re.compile(r'[A-Z]{3}_[0-9]{4}')
QUARTER_RE = re.compile(r'[0-9]{4}-Q[1-4]')
SHA256_RE = re.compile(r'[0-9a-f]{64}')                                                # as the build's
BUILT_AT_RE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z')  # as the build's
# python -I does not clear these; each would let the TLS layer trust or load something else (Orchestrator review W3)
TLS_OVERRIDES = ('SSL_CERT_FILE', 'SSL_CERT_DIR', 'OPENSSL_CONF', 'OPENSSL_MODULES', 'OPENSSL_ENGINES')
TOKEN_RE = re.compile(r'[A-Za-z0-9_.\-]{8,200}')    # no whitespace or control character: no header injection
TIMEOUT_SECONDS = 60
PACE_SECONDS = 0.5
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (2.0, 5.0)
MAX_RESPONSE_BYTES = 8_000_000   # the build refuses a file over 8,000,000 bytes, so the fetch does too (review 7)
CRED_TYPE_GENERIC = 1
CRED_MAX_BLOB = 2560
ERROR_NOT_FOUND = 1168
LEFTOVER_EXIT = 5                # a leftover .part file: not "try again later" (exit 3), a person has to look
USER_AGENT = 'yappman-data-area-history/1'


class FetchError(Exception):
    """A refusal or a request problem. Carries a short code (and a status when there was one), never a URL or body."""

    def __init__(self, code: str, status: int | None = None, *, exit_code: int = 4) -> None:
        super().__init__(code)
        self.code, self.status, self.exit_code = code, status, exit_code

    def __str__(self) -> str:
        return self.code


def refused(code: str) -> FetchError:
    return FetchError(code, exit_code=2)


# ------------------------------------------------------------------------------ the secret

class Secret:
    """A token held so that print, repr, str, format and pickling cannot show it. `reveal()` is called in one place:
    the Authorization header in `Transport._once`."""

    __slots__ = ('_value',)
    registered: set[str] = set()

    def __init__(self, value: str) -> None:
        value = value.strip()
        if not TOKEN_RE.fullmatch(value):
            raise refused('token-malformed')
        object.__setattr__(self, '_value', value)
        Secret.registered.add(value)

    def reveal(self) -> str:
        return self._value

    def __len__(self) -> int:
        return len(self._value)

    def __repr__(self) -> str:
        return '<secret>'

    __str__ = __repr__

    def __format__(self, spec: str) -> str:
        return '<secret>'

    def __reduce__(self) -> Any:
        raise TypeError('a Secret is not serialised')

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError('a Secret is read-only')


def emit(line: str, *, stream: Any = None) -> None:
    """The only way this tool prints: a line that contains the token or the store's name is replaced."""
    if any(secret in line for secret in Secret.registered) or 'pp-district-table' in line or 'key-value-stores' in line:
        line = json.dumps({'status': 'suppressed', 'code': 'output-held-a-protected-value'})
    print(line, file=stream or sys.stdout)


# ------------------------------------------------------------------------------ the credential

def _credential_api() -> Any:
    """advapi32 with argtypes and restypes set; a separate function so tests can swap it. Not called by any test."""
    import ctypes
    from ctypes import wintypes

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD), ('TargetName', wintypes.LPWSTR),
                    ('Comment', wintypes.LPWSTR), ('LastWritten', wintypes.FILETIME),
                    ('CredentialBlobSize', wintypes.DWORD), ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)),
                    ('Persist', wintypes.DWORD), ('AttributeCount', wintypes.DWORD),
                    ('Attributes', ctypes.c_void_p), ('TargetAlias', wintypes.LPWSTR),
                    ('UserName', wintypes.LPWSTR)]

    advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)
    advapi32.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
    advapi32.CredReadW.restype = wintypes.BOOL
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    advapi32.CredFree.restype = None
    advapi32.CREDENTIALW = CREDENTIALW
    return advapi32


def credential_token() -> str | None:
    """The generic credential's password, read ONCE with CredReadW, for CREDENTIAL_TARGET only. None if absent or
    unusable. Refused inside a Claude Code session. Nothing is printed; the API's copy is zeroed before CredFree."""
    if os.environ.get('CLAUDECODE'):
        raise refused('refused-inside-claude-code')
    import ctypes
    api = _credential_api()
    pointer = ctypes.POINTER(api.CREDENTIALW)()
    if not api.CredReadW(CREDENTIAL_TARGET, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == ERROR_NOT_FOUND:
            return None
        raise refused('credential-unreadable')
    try:
        cred = pointer.contents
        size = cred.CredentialBlobSize
        if cred.Type != CRED_TYPE_GENERIC or not 0 < size <= CRED_MAX_BLOB or size % 2:
            return None
        try:
            return ctypes.string_at(cred.CredentialBlob, size).decode('utf-16-le')
        except UnicodeDecodeError:
            return None
    finally:
        try:
            blob, size = pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize
            if blob and 0 < size <= CRED_MAX_BLOB:
                ctypes.memset(blob, 0, size)
        finally:
            api.CredFree(pointer)


def read_token(reader: Callable[[], str | None] | None = None) -> Secret:
    """The read token as a Secret. Refuses (a code only) inside a Claude Code session, on a non-Windows Python, and
    when the credential is missing, empty, malformed or unreadable. `reader` is for the tests only."""
    if reader is None:
        if os.environ.get('CLAUDECODE'):
            raise refused('refused-inside-claude-code')
        if os.name != 'nt' or sys.platform != 'win32':
            raise refused('not-windows-python')
        reader = credential_token
    try:
        value = reader()
    except FetchError:
        raise
    except Exception:  # noqa: BLE001 - fail closed; the type is not kept (ctypes errors can carry addresses)
        raise refused('credential-unreadable') from None
    if not value or not value.strip():
        raise refused('no-credential')
    return Secret(value)


# ------------------------------------------------------------------------------ the HTTP layer

@dataclass(frozen=True)
class Response:
    status: int
    body: bytes = b''


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def tls_context() -> ssl.SSLContext:
    """Certificate and host name checked, TLS 1.2 or later, and no TLS key log (the default context writes one to
    SSLKEYLOGFILE outside isolated mode, which would let a packet capture show the Bearer header)."""
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.keylog_filename = None
    return context


def build_opener(https_handler: Any = None) -> urllib.request.OpenerDirector:
    """HTTPS only (no HTTP or file handler), no proxy from the environment, no redirect. `https_handler` is for the
    tests only (a handler that answers without a socket)."""
    opener = urllib.request.OpenerDirector()
    opener.add_handler(urllib.request.ProxyHandler({}))
    opener.add_handler(https_handler or urllib.request.HTTPSHandler(context=tls_context()))
    opener.add_handler(_NoRedirect())
    opener.add_handler(urllib.request.HTTPDefaultErrorHandler())
    opener.add_handler(urllib.request.HTTPErrorProcessor())
    return opener


def record_url(key: str) -> str:
    if key not in FIXED_KEYS and not RECORD_KEY_RE.fullmatch(key):
        raise refused('key-refused')
    return f'{STORE_URL}/records/{key}'


class Transport:
    """GET only, to the record URLs of the history keys only. `opener` and `sleep` are for the tests only."""

    def __init__(self, token: Secret, *, opener: Any = None, sleep: Callable[[float], None] = time.sleep) -> None:
        self._token, self._opener, self._sleep = token, opener, sleep
        self._last: float | None = None
        self.requests: list[str] = []          # the keys asked for, in order (for the tests)
        self.limit = START_REQUESTS            # raised once, after the index is read, to the cap computed from it

    def __repr__(self) -> str:
        return 'Transport(api.apify.com)'

    def _once(self, key: str) -> Response:
        if self._last is not None and time.monotonic() - self._last < PACE_SECONDS:
            self._sleep(PACE_SECONDS)
        self._last = time.monotonic()
        url = record_url(key)
        if any(c in url for c in '?#%\\') or '..' in url or not url.startswith('https://'):
            raise refused('url-refused')
        headers = {'Accept': '*/*', 'User-Agent': USER_AGENT, 'Authorization': 'Bearer ' + self._token.reveal()}
        request = urllib.request.Request(url, headers=headers, method='GET')
        if len(self.requests) >= self.limit:
            raise refused('request-cap')
        self.requests.append(key)
        try:
            with (self._opener or build_opener()).open(request, timeout=TIMEOUT_SECONDS) as reply:
                status = int(reply.status)
                data = reply.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            status = int(error.code)
            error.close()
            if 300 <= status < 400:
                raise FetchError('redirect-refused', status) from None
            return Response(status)
        except Exception:  # noqa: BLE001 - the type, URL and message are dropped: a library error can echo a request
            raise FetchError('network-failure') from None
        if 300 <= status < 400:
            raise FetchError('redirect-refused', status)
        if len(data) > MAX_RESPONSE_BYTES:
            raise FetchError('response-too-large', status)
        return Response(status, data)

    def get(self, key: str) -> bytes | None:
        """The record's bytes, None for 404. Retries 429 and 5xx; any other status is an error."""
        for attempt in range(MAX_ATTEMPTS):
            reply = self._once(key)
            if reply.status == 200:
                return reply.body
            if reply.status == 404:
                return None
            if reply.status != 429 and reply.status < 500:
                raise FetchError('unexpected-status', reply.status)
            if attempt + 1 < MAX_ATTEMPTS:
                self._sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
        raise FetchError('retries-exhausted', reply.status)


# ------------------------------------------------------------------------------ the run

def state_facts(raw: bytes | None) -> dict[str, Any]:
    """AH_STATE's fields that the build checks; FetchError (exit 3) when it is missing or not a version 1 state."""
    if raw is None:
        raise FetchError('no-history-yet', 404, exit_code=3)
    try:
        state = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise FetchError('state-not-json', exit_code=3) from None
    if not isinstance(state, dict) or state.get('v') != 1:
        raise FetchError('state-not-version-1', exit_code=3)
    names = ('month', 'lastYear', 'lastQuarter', 'postcodeRelease', 'regionLookupSha256', 'builtAt',
             'authorities', 'regions', 'files', 'rows')
    facts = {k: state.get(k) for k in names}
    if not (isinstance(facts['month'], str) and MONTH_RE.fullmatch(facts['month'])
            and type(facts['lastYear']) is int and 1995 <= facts['lastYear'] <= 2100
            and isinstance(facts['lastQuarter'], str) and QUARTER_RE.fullmatch(facts['lastQuarter'])
            and isinstance(facts['postcodeRelease'], str) and RELEASE_RE.fullmatch(facts['postcodeRelease'])
            and isinstance(facts['regionLookupSha256'], str) and SHA256_RE.fullmatch(facts['regionLookupSha256'])
            and isinstance(facts['builtAt'], str) and BUILT_AT_RE.fullmatch(facts['builtAt'])
            and all(type(facts[k]) is int and 0 <= facts[k] < 10_000_000 for k in ('authorities', 'regions', 'files', 'rows'))):
        raise FetchError('state-incomplete', exit_code=3)
    return facts


def index_bases(raw: bytes | None) -> list[str]:
    """The base keys ah_index.json lists: each one of the known shapes, once each, at most MAX_BASES."""
    if raw is None:
        raise FetchError('index-missing', 404, exit_code=3)
    try:
        index = json.loads(raw.decode('utf-8'))
        bases = [entry['key'] for entry in index['files']]
    except (UnicodeDecodeError, ValueError, KeyError, TypeError):
        raise FetchError('index-not-usable', exit_code=3) from None
    if not (0 < len(bases) <= MAX_BASES and all(isinstance(b, str) and BASE_KEY_RE.fullmatch(b) for b in bases) and len(set(bases)) == len(bases)):
        raise FetchError('index-keys-refused', exit_code=3)
    return bases


def run(args: argparse.Namespace, transport: Transport, root: Path) -> dict[str, Any]:
    first = transport.get('AH_STATE')
    facts = state_facts(first)
    if args.dry_run:
        return {'status': 'dry-run', 'state': facts, 'saved': None}
    index_raw = transport.get('ah_index.json')
    bases = index_bases(index_raw)
    if facts['files'] != len(bases):
        raise FetchError('index-files-mismatch', exit_code=3)
    transport.limit = min(HARD_MAX_REQUESTS, 2 + 2 + 2 * len(bases) + 10)
    files: dict[str, bytes] = {'AH_STATE.json': first, 'ah_index.json': index_raw}
    for base in bases:
        for ext in ('json', 'csv'):
            body = transport.get(f'{base}.{ext}')
            if body is None:
                raise FetchError('file-missing', 404, exit_code=3)
            files[f'{base}.{ext}'] = body
            if sum(len(held) for held in files.values()) > MAX_TOTAL_BYTES:
                raise FetchError('total-size-refused', exit_code=3)
    if transport.get('AH_STATE') != first or transport.get('ah_index.json') != index_raw:
        raise FetchError('state-changed-during-fetch', exit_code=3)
    folder = root / INCOMING
    check_incoming(root)                  # also done before the token is read; repeated here in case it changed since
    folder.mkdir(parents=True, exist_ok=True)
    check_incoming(root)
    if any(entry.name not in files for entry in folder.iterdir()):
        raise FetchError('stale-files-in-incoming', exit_code=3)   # clear the folder by hand, then run again
    for name, body in files.items():
        target = folder / name
        temporary = target.with_name(target.name + '.part')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o644)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(body)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        os.replace(temporary, target)
    sizes = [len(body) for body in files.values()]
    saved = {'files': len(files), 'bases': len(bases), 'totalBytes': sum(sizes), 'largestBytes': max(sizes),
             'indexSha256': hashlib.sha256(index_raw).hexdigest(), 'stateSha256': hashlib.sha256(first).hexdigest()}
    return {'status': 'fetched', 'state': facts, 'saved': saved, 'folder': str(INCOMING)}


def _is_link(path: Path) -> bool:
    """A symlink, junction or any other reparse point (Windows), checked without following it."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, 'st_file_attributes', 0) & reparse)


def refuse_links(root: Path, *relatives: Path) -> None:
    """Every folder from the repo root down to each path, and the path itself, must be a plain folder or file (W4)."""
    for relative in relatives:
        current = root
        for part in relative.parts:
            current = current / part
            if _is_link(current):
                raise FetchError('link-refused', exit_code=2)


def check_incoming(root: Path) -> None:
    """The folder and the files in it must be plain (no link or reparse point), and no .part file may be left over from
    an earlier run. Run BEFORE the token is read, so a refusal costs no credential access. A leftover .part has its own
    exit code (5): it needs a person to look at it and delete it by hand."""
    folder = root / INCOMING
    refuse_links(root, INCOMING)
    if folder.exists():
        for entry in folder.iterdir():
            refuse_links(root, INCOMING / entry.name)
            if entry.name.endswith('.part'):
                raise FetchError('part-file-left-over', exit_code=LEFTOVER_EXIT)


def is_this_repo(root: Path) -> bool:
    try:
        return (root / 'CNAME').read_text(encoding='utf-8').strip() == 'data.yappman.com'
    except OSError:
        return False


def main(argv: list[str] | None = None, *, reader: Callable[[], str | None] | None = None, opener: Any = None,
         root: Path = REPO, sleep: Callable[[float], None] = time.sleep) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true', help='read AH_STATE only and print its facts')
    mode.add_argument('--fetch', action='store_true', help='save AH_STATE, the index and every listed record')
    args = parser.parse_args(argv)
    real = reader is None or opener is None
    if os.environ.get('CLAUDECODE') and real:
        emit(json.dumps({'status': 'refused', 'code': 'refused-inside-claude-code'}))
        return 2
    if real and not sys.flags.isolated:
        emit(json.dumps({'status': 'refused', 'code': 'run-with-python-I'}))
        return 2
    # python -I does not clear these, and they would let another certificate authority be trusted for this request
    # (Orchestrator review W-c): refuse rather than send the token through a substituted trust store
    if real and any(os.environ.get(name) for name in TLS_OVERRIDES):
        emit(json.dumps({'status': 'refused', 'code': 'tls-override-set'}))
        return 2
    if not is_this_repo(root):
        emit(json.dumps({'status': 'refused', 'code': 'not-the-data-yappman-repo'}))
        return 2
    try:
        if args.fetch:
            check_incoming(root)              # before read_token: a link or a leftover .part never reaches the credential
        token = read_token(reader)
        result = run(args, Transport(token, opener=opener, sleep=sleep), root)
    except FetchError as error:
        line = {'status': 'refused' if error.exit_code == 2 else 'stopped', 'code': error.code, 'httpStatus': error.status}
        if error.exit_code == LEFTOVER_EXIT:
            line['hint'] = 'a .part file is left over in _incoming/sold-prices-area-history: check it, delete it by hand, then run again'
        emit(json.dumps(line))
        return error.exit_code
    except Exception as error:  # noqa: BLE001 - the type only
        emit(json.dumps({'status': 'failed', 'type': type(error).__name__}))
        return 4
    emit(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
