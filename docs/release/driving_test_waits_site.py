"""GB driving-test waits: the website build (no network, no token). Page /driving-test-wait-index/ and its dataset files.

Reads what fetch_driving_test_waits.py saved in _incoming/driving-test/ (DRT122F.ods, DRT121G.ods, DRT121A.ods and
FACTS.json), parses them with driving_test_waits.py (bounded ODS reader, schema guards), and writes the dataset files and
the marked regions of the page. Run from anywhere (paths are anchored to this repo):

    python -I -B docs/release/driving_test_waits_site.py --describe                  # sheet names + the first 4 rows of each sheet (titles, headers)
    python -I -B docs/release/driving_test_waits_site.py --check [--first-publish]   # every check; writes nothing
    python -I -B docs/release/driving_test_waits_site.py --publish [--first-publish]

Pattern: docs/release/authority_yield_site.py (rental-yield), same exit codes and same write discipline:
- plans everything in memory first (the page and sitemap text too) and writes only when the plan is complete; each file is
  written whole as <name>.part opened with O_EXCL, then moved into place; no folder or file on the way may be a link;
- exit 0 published, or nothing new (same month, vintage and read time as what is live); 2 refused (usage, wrong folder, a
  link or leftover .part file, --first-publish against a live table, missing incoming files); 3 a check failed, the layout
  changed, or the page template is broken: nothing written, what is live stays live. A changed header or an unknown code
  is exit 3, never a guess;
- the dated archive driving-test-waits-<YYYY-MM>-dvsa-<release date>.{csv,json} (and the same for -regions and -national)
  is written once and never rewritten; the -latest files are updated.
- builtAt is the fetch's read time (FACTS.json), not the build's clock, so a re-run on the same files changes nothing.

Title (decision D3, 26 Nov 2026): no composite "index" and no median of medians: tables, ranks and changes only. The URL
stays /driving-test-wait-index/. Not published by DVSA. No slot checking or booking availability anywhere.
Licence: Open Government Licence v3.0; attribution below, exact on the page, in the text companion and in the JSON-LD.
The layout the parser expects was confirmed on the real 11 Nov 2026 files: see driving_test_waits.py.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import html
import io
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import driving_test_waits as dtw  # noqa: E402
import dvsa_ods  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
INCOMING = Path('_incoming/driving-test')
OUT = Path('data/driving-test-waits')
PAGE = Path('driving-test-wait-index/index.html')
SITEMAP = Path('sitemap.xml')
PAGE_URL = 'https://data.yappman.com/driving-test-wait-index/'
SOURCE_PAGE = 'https://www.gov.uk/government/statistical-data-sets/driving-test-and-theory-test-data-cars'
FILES = {'DRT122F': 'DRT122F.ods', 'DRT121G': 'DRT121G.ods', 'DRT121A': 'DRT121A.ods'}
FACTS_FILE = 'FACTS.json'
DATASETS = ('driving-test-waits', 'driving-test-waits-regions', 'driving-test-national')
LATEST = 'driving-test-waits-latest'
TEXT_COMPANION = 'driving-test-waits.txt'
TITLE = 'Driving test waits in Great Britain, by test centre'
LICENCE = 'Open Government Licence v3.0'
LICENCE_SHORT = 'OGL v3.0'
LICENCE_URL = 'https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/'
OGL_LINE = 'Contains public sector information licensed under the Open Government Licence v3.0.'
ATTRIBUTION = (
    OGL_LINE,
    'Source: Driver and Vehicle Standards Agency (DVSA), Driving test and theory test data: cars, ' + SOURCE_PAGE + '.',
)
DESCRIPTION = ('Free driving test waits by test centre and region in Great Britain, from the DVSA figures published each month: median '
               'wait in weeks, the share of tests taken within 7 weeks, ranks and changes over 3, 6 and 12 months, as CSV and JSON under the '
               'Open Government Licence v3.0.')
METHOD = (
    'The waits are the Driver and Vehicle Standards Agency (DVSA) figures for car practical driving tests, as DVSA '
    'publishes them each month: table DRT122F by test centre and table DRT121G by region. medianWaitWeeks is DVSA\'s median '
    'wait in weeks; the share columns are DVSA\'s percentages of tests taken within 7 weeks, between 7 and 14 weeks, '
    'between 14 and 21 weeks and after more than 21 weeks. The only arithmetic here is rank and change: rank orders the open '
    'centres that have a median wait in a month, longest wait first, and centres with the same median share a rank; change3m, '
    'change6m and change12m are the month\'s median wait minus the same centre\'s (or region\'s) median wait 3, 6 and 12 '
    'months earlier, in weeks to two decimal places, and are blank when either month has no figure. DVSA\'s shorthand ([n] no '
    'tests conducted, [r] redacted because of 10 or fewer, [x] not available, [z] not applicable, [rv] revised, [c] '
    'confidential, and N/A) is kept in suppressed and nothing is filled in. A centre DVSA shows as closed has centreStatus '
    'closed and no rank; a centre DVSA marks closed in some months and open in others keeps one key, and changes are not adjusted '
    'for this. provisional is true for months DVSA publishes as provisional (data since April 2025, at the date of '
    'this release). This page is not published by DVSA and carries no endorsement from it. It is not a booking tool: it '
    'cannot be used to find or book a test.'
)
# (column, meaning): one source for the page's Columns table and the JSON-LD
_FIGURES = (
    ('medianWaitWeeks', 'DVSA\'s median wait for a test, in weeks'),
    ('shareWithin7Weeks', 'DVSA\'s percentage of tests taken within 7 weeks'),
    ('share7to14', 'DVSA\'s percentage taken between 7 and 14 weeks'),
    ('share14to21', 'DVSA\'s percentage taken between 14 and 21 weeks'),
    ('shareOver21', 'DVSA\'s percentage taken after more than 21 weeks'),
    ('slotsOvertime', 'Test slots provided through overtime'),
    ('slotsInWindow', 'Standard test slots DVSA offered in the next 24 weeks (18 weeks until May 2021), counted on the last Monday of the month'),
    ('slotsBooked', 'Of those, the number booked'),
    ('slotsAvailable', 'Of those, the number still available to book'),
    ('slotsAvailablePct', 'Of those, the percentage still available to book'),
    ('weeksTo10pcAvailability', 'Weeks until 10% or more of weekly test appointments are still available to book (the current week is week 1), as DVSA gives it'),
)
CENTRE_COLUMNS = (
    ('month', 'The month the figures are for (YYYY-MM)'),
    ('country', 'England, Scotland or Wales'),
    ('region', 'DVSA\'s region'),
    ('centreKey', 'A stable key from the region and the centre name: region.centre, lower case'),
    ('centre', 'The test centre\'s name as DVSA gives it, without the closed-centre prefix'),
    ('centreStatus', 'open, or closed when DVSA marks the centre closed'),
) + _FIGURES + (
    ('provisional', 'true when DVSA publishes the month as provisional'),
    ('suppressed', 'DVSA redaction codes kept as field=code, separated by semicolons; blank when none'),
    ('rank', 'Rank of the centre in that month by median wait, 1 = longest, among open centres with a median wait'),
    ('change3m', 'medianWaitWeeks minus the same centre\'s 3 months earlier, in weeks; blank if either is missing'),
    ('change6m', 'The same over 6 months'),
    ('change12m', 'The same over 12 months'),
    ('source', 'DVSA table the row comes from'),
    ('licence', 'OGL v3.0'),
    ('vintage', 'The date of the DVSA monthly release the file was built from (YYYY-MM-DD)'),
)
REGION_COLUMNS = (
    ('month', 'The month the figures are for (YYYY-MM)'),
    ('level', 'Country or Region, as DVSA gives it'),
    ('country', 'England, Scotland, Wales or Great Britain (a region carries its country)'),
    ('region', 'The country or region the row is for: Great Britain, England, Scotland, Wales or one of DVSA\'s regions'),
    ('testsConducted', 'Total tests conducted with an outcome'),
    ('testsPassed', 'Tests passed'),
    ('passRatePct', 'DVSA\'s pass rate in percent'),
) + tuple(c for c in _FIGURES) + (
    ('provisional', 'true when DVSA publishes the month as provisional'),
    ('suppressed', 'DVSA shorthand kept as field=code, separated by semicolons; blank when none'),
    ('change3m', 'medianWaitWeeks minus the same area\'s 3 months earlier, in weeks; blank if either is missing'),
    ('change6m', 'The same over 6 months'),
    ('change12m', 'The same over 12 months'),
    ('source', 'DVSA table the row comes from'),
    ('licence', 'OGL v3.0'),
    ('vintage', 'The date of the DVSA monthly release the file was built from (YYYY-MM-DD)'),
)
NATIONAL_COLUMNS = (
    ('interval', 'Financial Quarter or Financial Year, as DVSA gives it'),
    ('period', 'The quarter or year as DVSA writes it, e.g. 2026 to 2027 Q1 April to June'),
    ('testsConducted', 'Tests conducted, as DVSA gives it'),
    ('testsPassed', 'Tests passed, as DVSA gives it'),
    ('passRatePct', 'DVSA\'s pass rate in percent'),
    ('suppressed', 'DVSA redaction codes kept as field=code; blank when none'),
    ('source', 'DVSA table the row comes from'),
    ('licence', 'OGL v3.0'),
    ('vintage', 'The date of the DVSA monthly release the file was built from (YYYY-MM-DD)'),
)
COLUMN_SETS = {'driving-test-waits': CENTRE_COLUMNS, 'driving-test-waits-regions': REGION_COLUMNS,
               'driving-test-national': NATIONAL_COLUMNS}
# A note shown beside a centre on the page, where the data alone could mislead: a fixed lead sentence of what DVSA says (its Notes
# sheet says nothing about the LGV centres, read 26 Nov 2026), then figures computed from the rows at build time (note_text).
# No guesses about what the centre is.
CENTRE_NOTES = {
    'Carlisle LGV (Cars)': (
        'note-lgv-cars',
        'DVSA lists Carlisle LGV (Cars) separately from Carlisle, and its notes do not explain the name.'),
}
NOT_MEASURED = ('source', 'licence', 'vintage')    # columns that describe the file, not what was measured (not in variableMeasured)
NATIONAL_QUARTERS_SHOWN = 8       # the page lists every financial year and the latest 8 quarters; the files hold all
JSON_MONTHS = 24                  # the centre JSON holds the latest 24 months only (served-tree size); the CSV holds all
MIN_CENTRES, MAX_CENTRES = 150, 500   # open and closed centre rows in any month: far outside is a fault, not a change
MONTH_ROW_CHANGE = 0.20
ROW_CHANGE_LIMIT = 0.20
MAX_FILE_BYTES = 40_000_000
CLOCK_SKEW_SECONDS = 3600
MONTH_RE = re.compile(r'[0-9]{4}-(?:0[1-9]|1[0-2])')
DATE_RE = re.compile(r'[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])')
BUILT_AT_RE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z')
SHA_RE = re.compile(r'[0-9a-f]{64}')
ARCHIVE_RE = re.compile(r'(?P<stem>driving-test-waits|driving-test-waits-regions|driving-test-national)-(?P<month>[0-9]{4}-(?:0[1-9]|1[0-2]))'
                        r'-dvsa-(?P<release>[0-9]{4}-[0-9]{2}-[0-9]{2})\.(?:csv|json)')
MONTH_NAMES = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
               'November', 'December')


class CheckFailed(Exception):
    def __init__(self, check: int, reason: str, *, refused: bool = False) -> None:
        super().__init__(f'check {check}: {reason}')
        self.check, self.refused = check, refused


class TemplateBroken(Exception):
    """The page or sitemap does not have the marked places the build fills."""


class Refused(Exception):
    def __init__(self, code: str, where: str = '') -> None:
        super().__init__(code)
        self.code, self.where = code, where


# ------------------------------------------------------------------------------ files and links

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
                raise Refused('link-refused', str(current.relative_to(root)))


def is_this_repo(root: Path) -> bool:
    try:
        return (root / 'CNAME').read_text(encoding='utf-8').strip() == 'data.yappman.com'
    except OSError:
        return False


def _replace(root: Path, path: Path, data: bytes) -> None:
    refuse_links(root, path.relative_to(root))
    temporary = path.with_name(path.name + '.part')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o644)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, path)


# ------------------------------------------------------------------------------ the incoming facts

def _no_repeats(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError('repeated key')
    return dict(pairs)


def load_facts(raw: bytes, files: dict[str, bytes]) -> dict[str, Any]:
    """FACTS.json (written by the fetch tool) checked against the three files' bytes."""
    try:
        facts = json.loads(raw.decode('utf-8'), object_pairs_hook=_no_repeats)
    except (UnicodeDecodeError, ValueError):
        raise CheckFailed(1, 'FACTS.json is not strict JSON') from None
    if not isinstance(facts, dict) or set(facts) != {'v', 'releaseDate', 'lastUpdated', 'readAt', 'files'} or facts['v'] != 1:
        raise CheckFailed(1, 'FACTS.json does not have exactly its keys')
    for key in ('releaseDate', 'lastUpdated'):
        if not (isinstance(facts[key], str) and DATE_RE.fullmatch(facts[key])):
            raise CheckFailed(1, f'FACTS.{key} is not a date')
    if not (isinstance(facts['readAt'], str) and BUILT_AT_RE.fullmatch(facts['readAt'])):
        raise CheckFailed(1, 'FACTS.readAt is malformed')
    listed = facts['files']
    if not isinstance(listed, dict) or set(listed) not in (set(FILES), set(FILES) | {'DRT121B'}):   # DRT121B is fetched, not read in v1
        raise CheckFailed(1, 'FACTS.files does not name the tables')
    for table, entry in listed.items():
        if not (isinstance(entry, dict) and set(entry) == {'bytes', 'sha256'} and type(entry['bytes']) is int
                and isinstance(entry['sha256'], str) and SHA_RE.fullmatch(entry['sha256'])):
            raise CheckFailed(1, f'FACTS.files.{table} is malformed')
    for table, data in files.items():
        entry = listed[table]
        if not (isinstance(entry, dict) and set(entry) == {'bytes', 'sha256'} and type(entry['bytes']) is int
                and isinstance(entry['sha256'], str) and SHA_RE.fullmatch(entry['sha256'])):
            raise CheckFailed(1, f'FACTS.files.{table} is malformed')
        if entry['bytes'] != len(data) or entry['sha256'] != hashlib.sha256(data).hexdigest():
            raise CheckFailed(1, f'{table} is not the file FACTS.json describes (size or SHA-256 differs)')
    return facts


# ------------------------------------------------------------------------------ the table

@dataclass(frozen=True)
class Table:
    month: str
    vintage: str
    facts: dict[str, Any]
    centres: list[dtw.WaitRow]
    regions: list[dtw.WaitRow]
    national: list[dict[str, Any]]
    files: dict[str, tuple[bytes, bytes]]          # stem -> (json bytes, csv bytes)
    document: dict[str, Any]                       # the centre JSON document (for the page and the checks)
    rows_all: int


def _cell(value: Any) -> str:
    if value is None:
        return ''
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    return str(value)


def _suppressed_text(codes: dict[str, str], order: tuple[str, ...]) -> str:
    return ';'.join(f'{name}={codes[name]}' for name in order if name in codes)


def centre_record(row: dtw.WaitRow, vintage: str) -> dict[str, Any]:
    v = row.values
    return {
        'month': row.month, 'country': row.country, 'region': row.region, 'centreKey': row.centreKey,
        'centre': row.centre, 'centreStatus': row.centreStatus,
        **{name: v[name] for name, _ in _FIGURES},
        'provisional': row.provisional, 'suppressed': _suppressed_text(row.suppressed, dtw.NUMERIC_FIELDS) or None,
        'rank': row.rank, 'change3m': row.change3m, 'change6m': row.change6m, 'change12m': row.change12m,
        'source': 'DRT122F', 'licence': LICENCE_SHORT, 'vintage': vintage,
    }


def region_record(row: dtw.WaitRow, vintage: str) -> dict[str, Any]:
    v = row.values
    return {
        'month': row.month, 'level': row.level, 'country': row.country, 'region': row.region,
        **{name: v[name] for name in ('testsConducted', 'testsPassed', 'passRatePct')},
        **{name: v[name] for name, _ in _FIGURES},
        'provisional': row.provisional, 'suppressed': _suppressed_text(row.suppressed, dtw.REGION_FIELDS) or None,
        'change3m': row.change3m, 'change6m': row.change6m, 'change12m': row.change12m,
        'source': 'DRT121G', 'licence': LICENCE_SHORT, 'vintage': vintage,
    }


def national_record(item: dict[str, Any], vintage: str) -> dict[str, Any]:
    order = ('testsConducted', 'testsPassed', 'passRatePct')
    return {'interval': item['interval'], 'period': item['period'], 'testsConducted': item['testsConducted'],
            'testsPassed': item['testsPassed'], 'passRatePct': item['passRatePct'],
            'suppressed': _suppressed_text(item['suppressed'], order) or None,
            'source': 'DRT121A', 'licence': LICENCE_SHORT, 'vintage': vintage}


def _csv_bytes(columns: tuple[tuple[str, str], ...], records: list[dict[str, Any]]) -> bytes:
    out = io.StringIO(newline='')
    writer = csv.writer(out, lineterminator='\n')
    names = [n for n, _ in columns]
    writer.writerow(names)
    for record in records:
        writer.writerow([_cell(record[n]) for n in names])
    return out.getvalue().encode('utf-8')


def _json_bytes(table_meta: dict[str, Any], columns: tuple[tuple[str, str], ...],
                records: list[dict[str, Any]]) -> bytes:
    document = {**table_meta, 'columns': [n for n, _ in columns], 'rows': records}
    return (json.dumps(document, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')


def build_table(facts: dict[str, Any], files: dict[str, bytes]) -> Table:
    """Parse, derive and serialise. Raises dtw.LayoutError (exit 3) from the parsers."""
    centres = dtw.read_table(files['DRT122F'], dtw.parse_centres)
    region_country: dict[str, str] = {}
    for row in centres:
        region_country.setdefault(row.region, row.country)
    regions = dtw.read_table(files['DRT121G'], dtw.parse_regions, region_country)
    national = dtw.read_table(files['DRT121A'], dtw.parse_national)
    dtw.derive(centres)
    dtw.derive(regions)
    vintage, month = facts['releaseDate'], max(r.month for r in centres)
    order = lambda r: (r.month, r.country, r.region, r.centre or '')           # noqa: E731
    centres.sort(key=order)
    regions.sort(key=order)
    base = {'v': 1, 'month': month, 'vintage': vintage, 'lastUpdated': facts['lastUpdated'], 'builtAt': facts['readAt'],
            'licence': LICENCE, 'attribution': list(ATTRIBUTION), 'method': METHOD}
    recent = {m for m in {r.month for r in centres} if m > dtw.month_minus(month, JSON_MONTHS)}
    c_all = [centre_record(r, vintage) for r in centres]
    c_json = [rec for rec in c_all if rec['month'] in recent]
    r_all = [region_record(r, vintage) for r in regions]
    n_all = [national_record(n, vintage) for n in national]
    out = {
        'driving-test-waits': (
            _json_bytes({**base, 'title': TITLE, 'jsonFromMonth': min(recent), 'rowsInCsv': len(c_all)}, CENTRE_COLUMNS, c_json),
            _csv_bytes(CENTRE_COLUMNS, c_all)),
        'driving-test-waits-regions': (
            _json_bytes({**base, 'title': 'Driving test waits in Great Britain, by region'},
                        REGION_COLUMNS, r_all),
            _csv_bytes(REGION_COLUMNS, r_all)),
        'driving-test-national': (
            _json_bytes({**base, 'title': 'Driving tests conducted and passed in Great Britain, by quarter'},
                        NATIONAL_COLUMNS, n_all),
            _csv_bytes(NATIONAL_COLUMNS, n_all)),
    }
    document = json.loads(out['driving-test-waits'][0].decode('utf-8'))
    return Table(month, vintage, facts, centres, regions, national, out, document, len(c_all))


# ------------------------------------------------------------------------------ checks

def live_table(root: Path) -> dict[str, Any] | None:
    path = root / OUT / f'{LATEST}.json'
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_bytes().decode('utf-8'))
        live = {k: document[k] for k in ('month', 'vintage', 'lastUpdated', 'builtAt')} | {'rows': document['rowsInCsv']}
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        raise CheckFailed(5, 'the live latest file cannot be read') from None
    if not (MONTH_RE.fullmatch(str(live['month'])) and DATE_RE.fullmatch(str(live['vintage']))
            and BUILT_AT_RE.fullmatch(str(live['builtAt'])) and type(live['rows']) is int):
        raise CheckFailed(5, 'the live latest file has a malformed month, vintage, builtAt or row count (edited by hand?)')
    return live


def check_table(table: Table, live: dict[str, Any] | None, first_publish: bool, now: datetime | None = None, *,
                min_centres: int | None = None, max_centres: int | None = None) -> None:
    """Every check, in order; raises CheckFailed at the first failure."""
    now = now or datetime.now(UTC)
    min_centres = MIN_CENTRES if min_centres is None else min_centres
    max_centres = MAX_CENTRES if max_centres is None else max_centres
    built = datetime.fromisoformat(table.facts['readAt'].replace('Z', '+00:00'))
    # 2. the months: plausible, one release behind, no gap, sane centre counts
    if table.month > now.strftime('%Y-%m') or (built - now).total_seconds() > CLOCK_SKEW_SECONDS:
        raise CheckFailed(2, 'the latest month or the read time is in the future')
    expected = dtw.month_minus(table.vintage[:7], 1)
    if table.month != expected:
        raise CheckFailed(2, f'the latest month is {table.month}, but a release dated {table.vintage} should end at {expected}')
    counts: dict[str, int] = {}
    for row in table.centres:
        counts[row.month] = counts.get(row.month, 0) + 1
    month = dtw.FIRST_MONTH
    while month <= table.month:
        if month not in counts:
            raise CheckFailed(2, f'no centre rows for {month}: a month is missing')
        if not min_centres <= counts[month] <= max_centres:
            raise CheckFailed(2, f'{counts[month]} centre rows in {month}, outside {min_centres} to {max_centres}')
        month = dtw.month_minus(month, -1)
    previous = counts.get(dtw.month_minus(table.month, 1))
    if previous and abs(counts[table.month] - previous) > MONTH_ROW_CHANGE * previous:
        raise CheckFailed(2, f'{counts[table.month]} centre rows in {table.month} against {previous} the month before')
    if max(r.month for r in table.regions) != table.month:
        raise CheckFailed(2, 'the regional table does not end at the same month as the centre table')
    if not table.national:
        raise CheckFailed(2, 'the national table is empty')
    # 3. rows: a centre has at most one key per month and a country matching its region everywhere
    country_of: dict[str, str] = {}
    for row in table.centres:
        if country_of.setdefault(row.region, row.country) != row.country:
            raise CheckFailed(3, f'a region ({row.region}) appears under two countries')
    for row in table.centres:
        if row.centreStatus == 'closed' and row.rank is not None:
            raise CheckFailed(3, 'a closed centre has a rank')
    # 5. not older than what is live; a first publish only when nothing is live
    if live is None:
        if not first_publish:
            raise CheckFailed(5, 'nothing is live: run with --first-publish for the first table', refused=True)
    else:
        if first_publish:
            raise CheckFailed(5, '--first-publish refused: a table is already live', refused=True)
        if (table.month, table.vintage) < (live['month'], live['vintage']):
            raise CheckFailed(5, f'the table ({table.month}, release {table.vintage}) is older than the live one')
        if live['rows'] and abs(table.rows_all - live['rows']) > ROW_CHANGE_LIMIT * live['rows']:
            raise CheckFailed(6, f'{table.rows_all} rows against {live["rows"]} live: more than a {ROW_CHANGE_LIMIT:.0%} change')


# ------------------------------------------------------------------------------ the page

def _size(n: int) -> str:
    return f'{n / 1_000_000:.1f} MB' if n >= 100_000 else f'{max(1, round(n / 1000))} KB'


def _region(text: str, name: str, content: str) -> str:
    start, end = f'<!-- driving-waits:{name} -->', f'<!-- /driving-waits:{name} -->'
    if text.count(start) != 1 or text.count(end) != 1 or text.index(start) > text.index(end):
        raise TemplateBroken(f'the page has no single {name} region')
    head, rest = text.split(start)
    _, tail = rest.split(end)
    return f'{head}{start}\n{content}{end}{tail}'


def month_days(month: str) -> int:
    return calendar.monthrange(int(month[:4]), int(month[5:7]))[1]


def month_name(month: str) -> str:
    return f'{MONTH_NAMES[int(month[5:7]) - 1]} {month[:4]}'


def _one_dp(value: Any) -> Decimal:
    """DVSA's display precision: one decimal place, half up, from the value's shortest text (the files keep full values)."""
    return Decimal(str(value)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)


def _weeks(value: Any) -> str:
    return '&ndash;' if value is None else f'{_one_dp(value)}'


def _pct(value: Any) -> str:
    return '&ndash;' if value is None else f'{_one_dp(value)}%'


def _change(value: Any) -> str:
    if value is None:
        return '&ndash;'
    shown = _one_dp(value)
    return '0.0' if shown == 0 else f'{shown:+}'.replace('-', '&minus;')


def _mark(centre: str | None) -> str:
    """The footnote marker after a centre's name, when it has a note."""
    note = CENTRE_NOTES.get(centre or '')
    return '' if note is None else f'<sup><a href="#{note[0]}">{list(CENTRE_NOTES).index(centre) + 1}</a></sup>'


def note_text(centres: list[dtw.WaitRow], month: str, name: str, lead: str) -> str:
    """The note for one centre: its fixed lead sentence, then figures worked out from the rows (never typed in, so they cannot
    go stale). Raises CheckFailed when the centre has no row at all, since the figures then cannot be computed."""
    own = [r for r in centres if r.centre == name]
    if not own:
        raise CheckFailed(3, f'the note for {name} cannot be computed: the centre has no rows')
    total = len({r.month for r in centres})
    first = min(r.month for r in own)
    sentence = f'It has a row in {len({r.month for r in own}):,} of the {total:,} months in this table (the first is {month_name(first)}), and DVSA '
    latest = [r for r in own if r.month == month]
    if not latest:
        sentence += f'has no row for it in {month_name(month)}.'
    elif latest[0].values.get('slotsInWindow') is None:
        sentence += f'gives no slot figures for it in {month_name(month)}.'
    else:
        sentence += f'gives {latest[0].values["slotsInWindow"]:,} standard test slots in the booking window for it in {month_name(month)}.'
    return f'{lead} {sentence}'


def _footnotes(table: Table, shown: set[str | None]) -> str:
    return ''.join(f'<p class="note" id="{note[0]}"><sup>{i}</sup> {html.escape(note_text(table.centres, table.month, name, note[1]))}</p>\n'
                   for i, (name, note) in enumerate(CENTRE_NOTES.items(), start=1) if name in shown)


def headline(table: Table) -> str:
    """The two-sentence summary from the data: the longest and the shortest median wait among open centres."""
    rows = [r for r in table.centres if r.month == table.month and r.centreStatus == 'open' and r.values['medianWaitWeeks'] is not None]
    if not rows:
        return ''
    top = max(r.values['medianWaitWeeks'] for r in rows)
    bottom = min(r.values['medianWaitWeeks'] for r in rows)
    longest = sorted((r for r in rows if r.values['medianWaitWeeks'] == top), key=lambda r: (r.region, r.centre))
    shortest = sorted((r for r in rows if r.values['medianWaitWeeks'] == bottom), key=lambda r: (r.region, r.centre))

    def who(group: list[dtw.WaitRow]) -> str:
        first = f'{html.escape(group[0].centre or "")}{_mark(group[0].centre)} ({html.escape(group[0].region)})'
        return first if len(group) == 1 else f'{first} and {len(group) - 1} other centre{"s" if len(group) > 2 else ""} with the same median'
    return (f'<p class="lead">In {month_name(table.month)}, among the {len(rows):,} open test centres with a median wait, the longest was '
            f'{_weeks(top)} weeks at {who(longest)}. The shortest was {_weeks(bottom)} weeks at {who(shortest)}.</p>\n')


def render_regions(table: Table, sizes: dict[str, int]) -> dict[str, str]:
    d, e = table.document, html.escape
    latest = [r for r in table.centres if r.month == table.month]
    summary = (f'<p>Latest data: {e(month_name(table.month))}, from the DVSA release of {e(table.vintage)} (gov.uk page last updated '
               f'{e(table.facts["lastUpdated"])}); {len(latest):,} test centres that month and {table.rows_all:,} centre-month rows since '
               f'{e(month_name(dtw.FIRST_MONTH))}. Read from DVSA on {e(table.facts["readAt"][:10])}.</p>\n')
    lines = ['<div class="table-wrap"><table><thead><tr><th>File</th><th>Month</th><th>DVSA release</th><th>Size</th></tr></thead>', '<tbody>']
    for stem in DATASETS:
        for ext in ('csv', 'json'):
            name = f'{stem}-latest.{ext}'
            lines.append(f'<tr><td><a href="/data/driving-test-waits/{name}">{name}</a> (latest)</td><td>{e(table.month)}</td>'
                         f'<td>{e(table.vintage)}</td><td>{_size(sizes[name])}</td></tr>')
    archives = sorted({m.group('stem', 'month', 'release') for n in sizes if (m := ARCHIVE_RE.fullmatch(n))},
                      key=lambda t: (t[1], t[2], t[0]), reverse=True)
    for stem, month, release in archives:
        for ext in ('csv', 'json'):
            name = f'{stem}-{month}-dvsa-{release}.{ext}'
            lines.append(f'<tr><td><a href="/data/driving-test-waits/{name}">{name}</a></td><td>{e(month)}</td><td>{e(release)}</td>'
                         f'<td>{_size(sizes[name])}</td></tr>')
    lines.append('</tbody></table></div>')
    lines.append(f'<p><a href="/data/driving-test-waits/{TEXT_COMPANION}">{TEXT_COMPANION}</a> (text companion, {_size(sizes[TEXT_COMPANION])})</p>')
    centres = sorted((r for r in latest if r.centreStatus == 'open'),
                     key=lambda r: (r.rank is None, r.rank or 0, r.region, r.centre or ''))
    rows = ['<div class="table-wrap"><table><thead><tr><th>Rank</th><th>Test centre</th><th>Region</th><th>Median wait (weeks)</th>'
            '<th>Taken within 7 weeks</th><th>Change over 12 months (weeks)</th></tr></thead>', '<tbody>']
    for r in centres:
        provisional = '' if not r.provisional else ' <span class="meta">(provisional)</span>'
        rows.append(f'<tr><td>{r.rank if r.rank is not None else "&ndash;"}</td><td>{e(r.centre or "")}{_mark(r.centre)}</td><td>{e(r.region)}</td>'
                    f'<td>{_weeks(r.values["medianWaitWeeks"])}{provisional}</td><td>{_pct(r.values["shareWithin7Weeks"])}</td>'
                    f'<td>{_change(r.change12m)}</td></tr>')
    rows.append('</tbody></table></div>')
    rows.append(_footnotes(table, {r.centre for r in centres}).rstrip('\n'))
    closed = [r for r in latest if r.centreStatus == 'closed']
    if closed:
        rows.append(f'<p class="note">{len(closed)} centre{"s" if len(closed) != 1 else ""} DVSA shows as closed this month '
                    f'{"are" if len(closed) != 1 else "is"} left out of the table and have no rank; {"they are" if len(closed) != 1 else "it is"} in the files.</p>')
    reg = ['<div class="table-wrap"><table><thead><tr><th>Area</th><th>Country</th><th>Median wait (weeks)</th>'
           '<th>Taken within 7 weeks</th><th>Change over 12 months (weeks)</th><th>Tests conducted</th><th>Pass rate</th></tr></thead>',
           '<tbody>']
    for r in sorted((r for r in table.regions if r.month == table.month), key=lambda r: (r.level != 'Country', r.region != 'Great Britain', r.country, r.region)):
        tests = r.values['testsConducted']
        reg.append(f'<tr><td>{e(r.region)}</td><td>{e(r.country)}</td><td>{_weeks(r.values["medianWaitWeeks"])}</td>'
                   f'<td>{_pct(r.values["shareWithin7Weeks"])}</td><td>{_change(r.change12m)}</td>'
                   f'<td>{"&ndash;" if tests is None else format(tests, ",")}</td><td>{_pct(r.values["passRatePct"])}</td></tr>')
    reg.append('</tbody></table></div>')
    nat = ['<div class="table-wrap"><table><thead><tr><th>Period</th><th>Tests conducted</th><th>Tests passed</th><th>Pass rate</th></tr></thead>', '<tbody>']
    quarters = [n for n in table.national if n['interval'] == 'Financial Quarter'][-NATIONAL_QUARTERS_SHOWN:]
    years = [n for n in table.national if n['interval'] == 'Financial Year']
    for n in years + quarters:
        nat.append(f'<tr><td>{e(n["period"])}</td><td>{"&ndash;" if n["testsConducted"] is None else format(n["testsConducted"], ",")}</td>'
                   f'<td>{"&ndash;" if n["testsPassed"] is None else format(n["testsPassed"], ",")}</td><td>{_pct(n["passRatePct"])}</td></tr>')
    nat.append('</tbody></table></div>')
    columns = ['<div class="table-wrap"><table><thead><tr><th>Column</th><th>Meaning</th></tr></thead>', '<tbody>']
    columns += [f'<tr><td><code>{e(n)}</code></td><td>{e(m)}</td></tr>' for n, m in CENTRE_COLUMNS]
    columns.append('</tbody></table></div>')
    ld = {
        '@context': 'https://schema.org', '@type': 'Dataset', 'name': TITLE, 'description': DESCRIPTION, 'url': PAGE_URL,
        'license': LICENCE_URL, 'isAccessibleForFree': True,
        'creator': {'@type': 'Organization', 'name': 'Yappman Data', 'url': 'https://data.yappman.com/',
                    'sameAs': ['https://www.youtube.com/@yappmandata', 'https://bsky.app/profile/yappmandata.bsky.social']},
        'isBasedOn': SOURCE_PAGE,
        'citation': ATTRIBUTION[1],
        'keywords': ['Great Britain', 'driving test', 'DVSA', 'test centre', 'waiting time', 'practical driving test'],
        'spatialCoverage': 'Great Britain', 'temporalCoverage': f'{dtw.FIRST_MONTH}-01/{table.month}-{month_days(table.month):02d}', 'dateModified': table.vintage,
        'distribution': [{'@type': 'DataDownload', 'name': f'{label}, {fmt.upper()}', 'encodingFormat': mime,
                          'contentUrl': f'https://data.yappman.com/data/driving-test-waits/{stem}-latest.{fmt}'}
                         for stem, label in (('driving-test-waits', 'Centres, all months'), ('driving-test-waits-regions', 'Regions'),
                                             ('driving-test-national', 'National by quarter'))
                         for fmt, mime in (('csv', 'text/csv'), ('json', 'application/json'))],
        'variableMeasured': [{'@type': 'PropertyValue', 'name': n, 'description': m} for n, m in CENTRE_COLUMNS if n not in NOT_MEASURED],
        'measurementTechnique': 'DVSA\'s published median waits and shares, with rank and changes in weeks as plain arithmetic.',
    }
    ld_text = json.dumps(ld, ensure_ascii=False, indent=2).replace('<', '\\u003c')
    attribution = ''.join(f'<p class="attribution">{e(a)}</p>\n' for a in ATTRIBUTION)
    return {
        'headline': headline(table), 'summary': summary, 'downloads': '\n'.join(lines) + '\n', 'attribution': attribution,
        'method': f'<p class="method">{e(METHOD)}</p>\n', 'centres': '\n'.join(rows) + '\n', 'regions': '\n'.join(reg) + '\n',
        'national': '\n'.join(nat) + '\n', 'columns': '\n'.join(columns) + '\n',
        'jsonld': f'<script type="application/ld+json">\n{ld_text}\n</script>\n',
    }


def text_companion(table: Table) -> bytes:
    lines = [
        TITLE, PAGE_URL, '',
        'Download: driving-test-waits-latest.csv and .json (test centres, all months in the CSV, the latest 24 months in the JSON),',
        'driving-test-waits-regions-latest.csv and .json (regions), driving-test-national-latest.csv and .json (quarterly, national).',
        f'Latest data: {month_name(table.month)}, from the DVSA release of {table.vintage}.',
        'Rank and the 3, 6 and 12-month changes are our arithmetic on DVSA\'s own figures; DVSA\'s redaction codes are kept, not filled in.',
        'Not published by DVSA, and carrying no endorsement from it. It cannot be used to find or book a test.', '',
        f'Licence: {LICENCE}, {LICENCE_URL}', *ATTRIBUTION, '',
        f'Cite: Yappman Data, {TITLE}, data to {table.month}, {PAGE_URL}, with the attribution above.', '',
    ]
    return '\n'.join(lines).encode('utf-8')


@dataclass(frozen=True)
class Plan:
    files: list[tuple[Path, bytes]]
    page: str
    sitemap: str
    done: list[str]


def plan_publish(root: Path, table: Table, today: str) -> Plan:
    """Everything the publish writes, worked out in memory; raises before anything is written."""
    out = root / OUT
    names = [f'{s}-latest.{e}' for s in DATASETS for e in ('json', 'csv')] + [TEXT_COMPANION]
    archives = [f'{s}-{table.month}-dvsa-{table.vintage}.{e}' for s in DATASETS for e in ('json', 'csv')]
    targets = [OUT / n for n in names + archives] + [PAGE, SITEMAP]
    refuse_links(root, *targets)
    for target in targets:
        if (root / target).with_name(target.name + '.part').exists():
            raise Refused('part-file-left-over', str(target) + '.part')
    sizes: dict[str, int] = {}
    for path in out.glob('driving-test-*.*') if out.exists() else ():
        if ARCHIVE_RE.fullmatch(path.name):
            sizes[path.name] = path.stat().st_size
    for stem in {n.rsplit('.', 1)[0] for n in sizes}:
        if not {f'{stem}.csv', f'{stem}.json'} <= set(sizes):
            raise CheckFailed(5, f'the archive {stem} has only one of its two files', refused=True)
    files: list[tuple[Path, bytes]] = []
    done: list[str] = []
    text = text_companion(table)
    for stem in DATASETS:
        json_bytes, csv_bytes = table.files[stem]
        pair = [(f'{stem}-{table.month}-dvsa-{table.vintage}.json', json_bytes), (f'{stem}-{table.month}-dvsa-{table.vintage}.csv', csv_bytes)]
        if all(n in sizes for n, _ in pair):
            if any((out / n).read_bytes() != data for n, data in pair):
                done.append(f'kept the {stem} {table.month} archive as first published (the latest files are updated)')
        else:
            for n, data in pair:
                files.append((out / n, data))
                sizes[n] = len(data)
                done.append(f'archived {n}')
        for ext, data in (('json', json_bytes), ('csv', csv_bytes)):
            files.append((out / f'{stem}-latest.{ext}', data))
            sizes[f'{stem}-latest.{ext}'] = len(data)
        done.append(f'wrote {stem}-latest.json and .csv')
    files.append((out / TEXT_COMPANION, text))
    sizes[TEXT_COMPANION] = len(text)
    try:
        page = (root / PAGE).read_text(encoding='utf-8')
        sitemap = (root / SITEMAP).read_text(encoding='utf-8')
    except OSError:
        raise TemplateBroken('the page or sitemap is missing') from None
    for name, content in render_regions(table, sizes).items():
        page = _region(page, name, content)
    for statement in ATTRIBUTION:                        # the attribution is shown on the page, word for word
        if f'<p class="attribution">{html.escape(statement)}</p>' not in page:
            raise CheckFailed(8, 'the attribution is not on the page')
    if OGL_LINE not in text.decode('utf-8') or OGL_LINE not in page or OGL_LINE not in table.files['driving-test-waits'][0].decode('utf-8'):
        raise CheckFailed(8, 'the OGL line is not in the page, the text companion and the JSON')
    if f'<p class="method">{html.escape(METHOD)}</p>' not in page:
        raise CheckFailed(8, 'the method is not on the page')
    pattern = re.compile(r'(<loc>' + re.escape(PAGE_URL) + r'</loc>\s*<lastmod>)[0-9-]{10}(</lastmod>)')
    if len(pattern.findall(sitemap)) != 1:
        raise TemplateBroken('sitemap.xml has no single entry for the page')
    done.append('updated driving-test-wait-index/index.html and its sitemap lastmod')
    return Plan(files, page, pattern.sub(rf'\g<1>{today}\g<2>', sitemap), done)


def write_plan(root: Path, plan: Plan) -> None:
    (root / OUT).mkdir(parents=True, exist_ok=True)
    refuse_links(root, OUT)
    for path, data in plan.files:
        _replace(root, path, data)
    _replace(root, root / PAGE, plan.page.encode('utf-8'))
    _replace(root, root / SITEMAP, plan.sitemap.encode('utf-8'))


# ------------------------------------------------------------------------------ the run

def read_incoming(root: Path) -> tuple[bytes, dict[str, bytes]]:
    refuse_links(root, INCOMING, *(INCOMING / n for n in (FACTS_FILE, *FILES.values())))
    try:
        facts = (root / INCOMING / FACTS_FILE).read_bytes()
        files = {table: (root / INCOMING / name).read_bytes() for table, name in FILES.items()}
    except OSError:
        raise Refused('incoming-files-missing', str(INCOMING)) from None
    if any(len(data) > MAX_FILE_BYTES for data in files.values()):
        raise CheckFailed(1, f'a file is larger than {MAX_FILE_BYTES} bytes')
    return facts, files


def describe(files: dict[str, bytes]) -> dict[str, Any]:
    """Sheet names, row counts and the first four non-empty rows of each sheet (titles and headers, at most a row of data)."""
    out: dict[str, Any] = {}
    for table, data in files.items():
        try:
            sheets = dvsa_ods.read_ods(data)
        except dvsa_ods.OdsError as error:
            out[table] = {'error': error.code}
            continue
        out[table] = {name: {'rows': len(rows), 'firstRows': [r[:20] for r in rows[:dtw.HEADER_SEARCH_ROWS] if r][:4]}
                      for name, rows in sheets.items()}
    return out


def main(argv: list[str] | None = None, *, root: Path = REPO, today: str | None = None, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--describe', action='store_true', help='print sheet names and the first rows of each sheet; writes nothing')
    mode.add_argument('--check', action='store_true', help='the checks only; writes nothing')
    mode.add_argument('--publish', action='store_true')
    parser.add_argument('--first-publish', action='store_true', help='only when no table is live yet')
    args = parser.parse_args(argv)
    if not is_this_repo(root):
        print(json.dumps({'status': 'refused', 'code': 'not-the-data-yappman-repo'}))
        return 2
    live = None
    try:
        facts_raw, files = read_incoming(root)
        if args.describe:
            print(json.dumps({'status': 'described', 'tables': describe(files)}, ensure_ascii=False))
            return 0
        facts = load_facts(facts_raw, files)
        live = live_table(root)
        table = build_table(facts, files)
        check_table(table, live, args.first_publish, now)
        if live is not None and (live['month'], live['vintage'], live['lastUpdated'], live['builtAt']) == (
                table.month, table.vintage, facts['lastUpdated'], facts['readAt']):
            print(json.dumps({'status': 'nothing-new', 'month': table.month, 'vintage': table.vintage}))
            return 0
        plan = plan_publish(root, table, today or datetime.now(UTC).date().isoformat())
    except dtw.LayoutError as failure:
        print(json.dumps({'status': 'held', 'code': 'layout', 'reason': failure.reason, 'live': live}))
        return 3
    except CheckFailed as failure:
        print(json.dumps({'status': 'refused' if failure.refused else 'held', 'check': failure.check, 'reason': str(failure), 'live': live}))
        return 2 if failure.refused else 3
    except Refused as refusal:
        print(json.dumps({'status': 'refused', 'code': refusal.code, 'where': refusal.where}))
        return 2
    except TemplateBroken as broken:
        print(json.dumps({'status': 'held', 'code': 'template-broken', 'reason': str(broken)}))
        return 3
    summary = {'month': table.month, 'vintage': table.vintage, 'lastUpdated': facts['lastUpdated'], 'rows': table.rows_all,
               'regionRows': len(table.regions), 'nationalRows': len(table.national), 'live': live}
    if args.check:
        print(json.dumps({'status': 'checks-passed', **summary, 'wouldDo': plan.done}))
        return 0
    write_plan(root, plan)
    print(json.dumps({'status': 'published', **summary, 'done': plan.done}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
