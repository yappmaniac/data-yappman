"""Median sold prices by postcode district: the website build (no network, no token).

Turns the three files that fetch_district_table.py saved (DT_STATE.json, table_latest.json, table_latest.csv) into
the download files and the page. Run from the repo root, after the fetch:

    python -I -B docs/release/district_table_site.py --check                    # the checks only, writes nothing
    python -I -B docs/release/district_table_site.py --publish [--first-publish]

Spec: Orchestrator drafts/sessions/property/district-table-design-4-nov.md, sections 2 (columns), 5 (attribution)
and 6 (URLs, checks, page text). What it does:
- Reads DT_STATE first and publishes only when all eight checks of section 6 pass; otherwise it writes nothing and
  what is live stays live (exit 3). Check 5 and 6 compare with the live latest file in data/sold-prices/.
- Writes data/sold-prices/district-medians-latest.{csv,json} and, once per month, the dated archive
  district-medians-<YYYY-MM>.{csv,json}. An archive file is never rewritten: a later build of the same month updates
  the latest files only and says so.
- Rewrites only the marked parts of sold-prices/index.html (the summary, the downloads list and the attribution,
  taken from the JSON) and the page's lastmod in sitemap.xml.
The files are published as fetched (byte for byte), so what was checked is what is served.

Exit codes: 0 published, or nothing new; 2 refused (usage, or --first-publish against a live table); 3 a check
failed, nothing written.
"""

from __future__ import annotations

import argparse
import csv
import decimal
import html
import io
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TABLE_VERSION = 2
TITLE = 'Median sold prices by postcode district, England and Wales'
LICENCE = 'Open Government Licence v3.0'
COLUMNS = (
    'month', 'periodFrom', 'periodTo', 'district', 'localAuthorityCodes', 'propertyType',
    'sales12m', 'median12m', 'lowerQuartile12m', 'upperQuartile12m', 'sales3m', 'median3m',
    'salesPrev12m', 'medianPrev12m', 'medianChangePct', 'lowSample',
)
COUNT_COLUMNS = ('sales12m', 'sales3m', 'salesPrev12m')
FIGURE_COLUMNS = ('median12m', 'lowerQuartile12m', 'upperQuartile12m', 'median3m', 'medianPrev12m')
PROPERTY_TYPES = frozenset({'all', 'detached', 'semi-detached', 'terraced', 'flat'})
ROW_CHANGE_LIMIT = 0.20          # check 6: the row count is within 20% of last month's
MAX_FILE_BYTES = 8_000_000       # the Actor refuses a table over this

MONTH_RE = re.compile(r'[0-9]{4}-(?:0[1-9]|1[0-2])')
DISTRICT_RE = re.compile(r'[A-Z]{1,2}[0-9][0-9A-Z]?')       # an outcode only: no sector, no full postcode
AUTHORITIES_RE = re.compile(r'(?:[EW][0-9]{8}(?:;[EW][0-9]{8})*)?')
ATTRIBUTION_STARTS = ('Contains HM Land Registry data', 'Local authority codes:')

INCOMING = Path('_incoming/sold-prices')
OUT = Path('data/sold-prices')
PAGE = Path('sold-prices/index.html')
SITEMAP = Path('sitemap.xml')
PAGE_URL = 'https://data.yappman.com/sold-prices/'
STATE_FILE, JSON_FILE, CSV_FILE = 'DT_STATE.json', 'table_latest.json', 'table_latest.csv'
LATEST = 'district-medians-latest'


class CheckFailed(Exception):
    """A check of section 6 failed. Carries the check number and a short reason, never a row."""

    def __init__(self, check: int, reason: str, *, refused: bool = False) -> None:
        super().__init__(f'check {check}: {reason}')
        self.check = check
        self.refused = refused      # a usage refusal (exit 2), not a held table (exit 3)


@dataclass(frozen=True)
class Table:
    state: dict[str, Any]
    document: dict[str, Any]
    json_bytes: bytes
    csv_bytes: bytes

    @property
    def month(self) -> str:
        return self.state['month']

    @property
    def rows(self) -> int:
        return self.state['rows']


def csv_cell(value: Any) -> str:
    """A cell as the Actor's table_csv writes it: null is empty, booleans are true/false, numbers as Python's str."""
    if value is None:
        return ''
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    return str(value)


def cell_matches(cell: str, value: Any) -> bool:
    """The CSV cell is the JSON value as table_csv writes it. Numbers are compared as numbers, so a JSON 3.0 that
    a store re-serialised as 3 still matches the CSV's 3.0; text, empty and true/false are compared exactly."""
    if value is None or type(value) is bool or isinstance(value, str):
        return cell == csv_cell(value)
    if type(value) in (int, float):
        try:
            return decimal.Decimal(cell) == decimal.Decimal(repr(value))
        except decimal.InvalidOperation:
            return False
    return False


def _is_count(value: Any) -> bool:
    return type(value) is int and value >= 0


def _is_number_or_empty(value: Any) -> bool:
    if value is None:
        return True
    if type(value) is int:
        return True
    return type(value) is float and math.isfinite(value)


def _load_json(raw: bytes, check: int, name: str) -> Any:
    try:
        return json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise CheckFailed(check, f'{name} is not valid UTF-8 JSON') from None


def check_table(state_raw: bytes, json_raw: bytes, csv_raw: bytes, live: dict[str, Any] | None,
                first_publish: bool) -> Table:
    """All eight checks of section 6, in order. Raises CheckFailed (number and reason) at the first failure."""
    state = _load_json(state_raw, 1, 'DT_STATE')
    if not isinstance(state, dict):
        raise CheckFailed(1, 'DT_STATE is not an object')
    for name, raw in (('table_latest.json', json_raw), ('table_latest.csv', csv_raw)):
        if len(raw) > MAX_FILE_BYTES:
            raise CheckFailed(1, f'{name} is larger than {MAX_FILE_BYTES} bytes')
    document = _load_json(json_raw, 1, 'table_latest.json')
    if not isinstance(document, dict):
        raise CheckFailed(1, 'table_latest.json is not an object')

    # 1. versions and columns
    if state.get('v') != TABLE_VERSION or document.get('v') != TABLE_VERSION:
        raise CheckFailed(1, f'DT_STATE.v and the JSON v must both be {TABLE_VERSION}')
    if document.get('columns') != list(COLUMNS):
        raise CheckFailed(1, 'the JSON columns are not the 16 names in order')

    # 2. the JSON and DT_STATE come from one build
    month, built_at, rows = state.get('month'), state.get('builtAt'), state.get('rows')
    if not (isinstance(month, str) and MONTH_RE.fullmatch(month)) or not isinstance(built_at, str) or not _is_count(rows):
        raise CheckFailed(2, 'DT_STATE has no month, builtAt or row count')
    if document.get('month') != month or document.get('builtAt') != built_at:
        raise CheckFailed(2, 'the JSON month or builtAt differs from DT_STATE')
    json_rows = document.get('rows')
    if not isinstance(json_rows, list) or len(json_rows) != rows:
        raise CheckFailed(2, 'the JSON row count differs from DT_STATE.rows')
    if document.get('title') != TITLE or document.get('licence') != LICENCE:
        raise CheckFailed(2, 'the JSON title or licence is not the expected one')

    # 3. the CSV is the same build, cell for cell
    try:
        csv_text = csv_raw.decode('utf-8')
    except UnicodeDecodeError:
        raise CheckFailed(3, 'table_latest.csv is not UTF-8') from None
    parsed = list(csv.reader(io.StringIO(csv_text, newline='')))
    if not parsed or parsed[0] != list(COLUMNS):
        raise CheckFailed(3, 'the CSV header is not the columns')
    body = parsed[1:]
    if len(body) != rows:
        raise CheckFailed(3, 'the CSV row count differs from DT_STATE.rows')
    for index, (cells, row) in enumerate(zip(body, json_rows), start=1):
        if not isinstance(row, dict) or len(row) != len(COLUMNS) or set(row) != set(COLUMNS):
            raise CheckFailed(3, f'JSON row {index} does not have the 16 keys')
        if not cells or cells[0] != month:
            raise CheckFailed(3, f'CSV row {index} has another month')
        if len(cells) != len(COLUMNS) or not all(cell_matches(cell, row[c]) for cell, c in zip(cells, COLUMNS)):
            raise CheckFailed(3, f'CSV row {index} differs from JSON row {index}')

    # 5. not older than what is live; a first publish only when nothing is live
    if live is None:
        if not first_publish:
            raise CheckFailed(5, 'nothing is live: run with --first-publish for the first table', refused=True)
    else:
        if first_publish:
            raise CheckFailed(5, '--first-publish refused: a table is already live', refused=True)
        if month < live['month']:
            raise CheckFailed(5, f'the table is for {month}, older than the live {live["month"]}')
        # 6. the row count is within 20% of last month's
        if abs(rows - live['rows']) > ROW_CHANGE_LIMIT * live['rows']:
            raise CheckFailed(6, f'{rows} rows against {live["rows"]} live: more than a {ROW_CHANGE_LIMIT:.0%} change')

    # 7. every cell has the expected kind (and, beyond the spec, no postcode or sector can slip in)
    for index, row in enumerate(json_rows, start=1):
        if row['month'] != month or row['propertyType'] not in PROPERTY_TYPES:
            raise CheckFailed(7, f'row {index}: month or property type')
        if not (isinstance(row['district'], str) and DISTRICT_RE.fullmatch(row['district'])):
            raise CheckFailed(7, f'row {index}: the district is not an outcode')
        if not (isinstance(row['localAuthorityCodes'], str) and AUTHORITIES_RE.fullmatch(row['localAuthorityCodes'])):
            raise CheckFailed(7, f'row {index}: the authority codes')
        for key in ('periodFrom', 'periodTo'):
            if not (isinstance(row[key], str) and MONTH_RE.fullmatch(row[key])):
                raise CheckFailed(7, f'row {index}: {key}')
        if not all(_is_count(row[c]) for c in COUNT_COLUMNS):
            raise CheckFailed(7, f'row {index}: a count is not a whole number')
        if not all(_is_number_or_empty(row[c]) for c in (*FIGURE_COLUMNS, 'medianChangePct')):
            raise CheckFailed(7, f'row {index}: a figure is not a number or empty')
        if type(row['lowSample']) is not bool:
            raise CheckFailed(7, f'row {index}: lowSample is not true or false')

    # 8. the attribution is present (the page shows it: see write_page)
    attribution = document.get('attribution')
    if not (isinstance(attribution, list) and len(attribution) == 2 and all(isinstance(a, str) for a in attribution)
            and all(a.startswith(s) for a, s in zip(attribution, ATTRIBUTION_STARTS))):
        raise CheckFailed(8, 'the two attribution statements are missing')
    return Table(state, document, json_raw, csv_raw)


def live_table(root: Path) -> dict[str, Any] | None:
    """The month, builtAt and row count of the live latest JSON, or None before the first publish."""
    path = root / OUT / f'{LATEST}.json'
    if not path.exists():
        return None
    document = json.loads(path.read_bytes().decode('utf-8'))
    return {'month': document['month'], 'builtAt': document['builtAt'], 'rows': len(document['rows'])}


def _size(n: int) -> str:
    return f'{n / 1_000_000:.1f} MB' if n >= 100_000 else f'{max(1, round(n / 1000))} KB'


def _months(root: Path) -> list[str]:
    found = set()
    for path in (root / OUT).glob('district-medians-*.json'):
        stem = path.stem.removeprefix('district-medians-')
        if MONTH_RE.fullmatch(stem):
            found.add(stem)
    return sorted(found, reverse=True)


def _region(text: str, name: str, content: str) -> str:
    start, end = f'<!-- district-table:{name} -->', f'<!-- /district-table:{name} -->'
    if text.count(start) != 1 or text.count(end) != 1 or text.index(start) > text.index(end):
        raise ValueError(f'the page has no single {name} region')
    head, rest = text.split(start)
    _, tail = rest.split(end)
    return f'{head}{start}\n{content}{end}{tail}'


def render_regions(root: Path, table: Table) -> dict[str, str]:
    d = table.document
    e = html.escape
    districts = table.state.get('districts')
    summary = (f'<p>Latest table: {e(d["month"])}, sales from {e(d["periodFrom"])} to {e(d["periodTo"])}; '
               f'{table.rows:,} rows'
               + (f' for {districts:,} districts' if _is_count(districts) else '')
               + f'. Built {e(d["builtAt"][:10])}.</p>\n')
    lines = ['<div class="table-wrap"><table><thead><tr><th>File</th><th>Month</th><th>Size</th></tr></thead>', '<tbody>']
    for ext in ('csv', 'json'):
        name = f'{LATEST}.{ext}'
        size = (root / OUT / name).stat().st_size
        lines.append(f'<tr><td><a href="/data/sold-prices/{name}">{name}</a> (latest)</td><td>{e(d["month"])}</td><td>{_size(size)}</td></tr>')
    for month in _months(root):
        for ext in ('csv', 'json'):
            name = f'district-medians-{month}.{ext}'
            path = root / OUT / name
            if path.exists():
                lines.append(f'<tr><td><a href="/data/sold-prices/{name}">{name}</a></td><td>{month}</td><td>{_size(path.stat().st_size)}</td></tr>')
    lines.append('</tbody></table></div>')
    attribution = ''.join(f'<p class="attribution">{e(a)}</p>\n' for a in d['attribution'])
    return {'summary': summary, 'downloads': '\n'.join(lines) + '\n', 'attribution': attribution}


def write_page(root: Path, table: Table, today: str) -> None:
    page = root / PAGE
    text = page.read_text(encoding='utf-8')
    for name, content in render_regions(root, table).items():
        text = _region(text, name, content)
    for statement in table.document['attribution']:      # check 8: the attribution is shown on the page
        if html.escape(statement) not in text:
            raise CheckFailed(8, 'the attribution is not on the page')
    page.write_text(text, encoding='utf-8', newline='\n')
    sitemap = root / SITEMAP
    raw = sitemap.read_text(encoding='utf-8')
    pattern = re.compile(r'(<loc>' + re.escape(PAGE_URL) + r'</loc>\s*<lastmod>)[0-9-]{10}(</lastmod>)')
    if len(pattern.findall(raw)) != 1:
        raise ValueError('sitemap.xml has no single entry for the page')
    sitemap.write_text(pattern.sub(rf'\g<1>{today}\g<2>', raw), encoding='utf-8', newline='')


def publish(root: Path, table: Table, today: str) -> list[str]:
    """Writes the files and the page. Returns what was done, one line each."""
    out = root / OUT
    out.mkdir(parents=True, exist_ok=True)
    done = []
    for ext, data in (('json', table.json_bytes), ('csv', table.csv_bytes)):
        archive = out / f'district-medians-{table.month}.{ext}'
        if not archive.exists():
            archive.write_bytes(data)
            done.append(f'archived {archive.name}')
        elif archive.read_bytes() != data:
            done.append(f'kept {archive.name} as first published (a later build of {table.month} updates the latest file only)')
        (out / f'{LATEST}.{ext}').write_bytes(data)
        done.append(f'wrote {LATEST}.{ext}')
    write_page(root, table, today)
    done.append('updated sold-prices/index.html and its sitemap lastmod')
    return done


def main(argv: list[str] | None = None, *, root: Path = Path('.'), today: str | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='the checks only; writes nothing')
    mode.add_argument('--publish', action='store_true')
    parser.add_argument('--first-publish', action='store_true', help='only when no table is live yet')
    args = parser.parse_args(argv)
    incoming = root / INCOMING
    try:
        raws = [(incoming / name).read_bytes() for name in (STATE_FILE, JSON_FILE, CSV_FILE)]
    except OSError:
        print(json.dumps({'status': 'refused', 'code': 'incoming-files-missing', 'folder': str(INCOMING)}))
        return 2
    live = live_table(root)
    try:
        table = check_table(*raws, live, args.first_publish)
    except CheckFailed as failure:
        print(json.dumps({'status': 'refused' if failure.refused else 'held', 'check': failure.check,
                          'reason': str(failure), 'live': live}))
        return 2 if failure.refused else 3
    if live is not None and live['month'] == table.month and live['builtAt'] == table.state['builtAt']:
        print(json.dumps({'status': 'nothing-new', 'month': table.month, 'builtAt': table.state['builtAt']}))
        return 0
    summary = {'month': table.month, 'builtAt': table.state['builtAt'], 'rows': table.rows, 'live': live}
    if args.check:
        print(json.dumps({'status': 'checks-passed', **summary}))
        return 0
    done = publish(root, table, today or datetime.now(UTC).date().isoformat())
    print(json.dumps({'status': 'published', **summary, 'done': done}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
