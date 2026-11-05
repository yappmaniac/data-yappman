"""Median sold prices by postcode district: the website build (no network, no token).

Turns the three files that fetch_district_table.py saved (DT_STATE.json, table_latest.json, table_latest.csv) into
the download files and the page. Run from anywhere (paths are anchored to this repo):

    python -I -B docs/release/district_table_site.py --check                    # the checks only, writes nothing
    python -I -B docs/release/district_table_site.py --publish [--first-publish]

Spec: Orchestrator drafts/sessions/property/district-table-design-4-nov.md, sections 2 (columns), 5 (attribution)
and 6 (URLs, checks, page text). What it does:
- Reads DT_STATE first and publishes only when all eight checks of section 6 pass; otherwise it writes nothing and
  what is live stays live (exit 3). Check 5 and 6 compare with the live latest file in data/sold-prices/. Beyond the
  spec (security review of 9a1dfd6, C3): no JSON object may repeat a key, DT_STATE and the JSON's top level have an
  exact key set with checked types, and each attribution statement must match its text in full (only the year, the
  build year, may vary), so what is checked is exactly what is served.
- Plans everything in memory first (the page and sitemap text included) and writes only when the plan is complete
  (review C2): the data files, then the page, then the sitemap.
- Writes data/sold-prices/district-medians-latest.{csv,json} and, once per month, the dated archive
  district-medians-<YYYY-MM>.{csv,json}. An archive file is never rewritten: a later build of the same month updates
  the latest files only and says so. A month with only one of its two archive files is refused.
- Rewrites only the marked parts of sold-prices/index.html (the summary, the downloads list and the attribution,
  taken from the JSON and escaped) and the page's lastmod in sitemap.xml.
The files are published as fetched (byte for byte).

Exit codes: 0 published, or nothing new; 2 refused (usage, wrong folder, or --first-publish against a live table);
3 a check failed or the page template is broken, nothing written.
"""

from __future__ import annotations

import argparse
import csv
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
LAG_MONTHS = 3
TITLE = 'Median sold prices by postcode district, England and Wales'
LICENCE = 'Open Government Licence v3.0'
COLUMNS = (
    'month', 'periodFrom', 'periodTo', 'district', 'localAuthorityCodes', 'propertyType',
    'sales12m', 'median12m', 'lowerQuartile12m', 'upperQuartile12m', 'sales3m', 'median3m',
    'salesPrev12m', 'medianPrev12m', 'medianChangePct', 'lowSample',
)
DOCUMENT_KEYS = frozenset({
    'v', 'title', 'month', 'periodFrom', 'periodTo', 'previousPeriodFrom', 'previousPeriodTo', 'threeMonthFrom',
    'lagMonths', 'postcodeRelease', 'builtAt', 'licence', 'attribution', 'method', 'columns', 'rows',
})
STATE_KEYS = frozenset({'v', 'month', 'postcodeRelease', 'builtAt', 'districts', 'rows'})
COUNT_COLUMNS = ('sales12m', 'sales3m', 'salesPrev12m')
FIGURE_COLUMNS = ('median12m', 'lowerQuartile12m', 'upperQuartile12m', 'median3m', 'medianPrev12m')
PROPERTY_TYPES = frozenset({'all', 'detached', 'semi-detached', 'terraced', 'flat'})
ROW_CHANGE_LIMIT = 0.20          # check 6: the row count is within 20% of last month's
MAX_FILE_BYTES = 8_000_000       # the Actor refuses a table over this
MAX_METHOD_CHARS = 1_000

MONTH_RE = re.compile(r'[0-9]{4}-(?:0[1-9]|1[0-2])')
BUILT_AT_RE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z')
RELEASE_RE = re.compile(r'[A-Z]{3}_[0-9]{4}')
DISTRICT_RE = re.compile(r'[A-Z]{1,2}[0-9][0-9A-Z]?')       # an outcode only: no sector, no full postcode
AUTHORITIES_RE = re.compile(r'(?:[EW][0-9]{8}(?:;[EW][0-9]{8})*)?')
NUMBER_CELL_RE = re.compile(r'-?[0-9]+(?:\.[0-9]+)?')
ATTRIBUTION_RES = (
    re.compile(r'Contains HM Land Registry data © Crown copyright and database right (?P<y>20[0-9]{2})\. '
               r'This data is licensed under the Open Government Licence v3\.0\.'),
    re.compile(r'Local authority codes: Source: Office for National Statistics licensed under the Open Government '
               r'Licence v3\.0\. Contains OS data © Crown copyright and database right (?P<y>20[0-9]{2})\. Contains '
               r'Royal Mail data © Royal Mail copyright and database right (?P<z>20[0-9]{2})\.'),
)

REPO = Path(__file__).resolve().parents[2]
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


class TemplateBroken(Exception):
    """The page or sitemap does not have the marked places the build fills."""


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
    """The CSV cell is the JSON value as table_csv writes it. Numbers are compared as numbers (a JSON 3.0 that a store
    re-serialised as 3 still matches the CSV's 3.0), but the cell must be a plain decimal: no sign other than a
    leading minus, no exponent, space or underscore. Text, empty and true/false are compared exactly."""
    if value is None or type(value) is bool or isinstance(value, str):
        return cell == csv_cell(value)
    if type(value) in (int, float) and NUMBER_CELL_RE.fullmatch(cell):
        from decimal import Decimal
        return Decimal(cell) == Decimal(repr(value))
    return False


def _is_count(value: Any) -> bool:
    return type(value) is int and value >= 0


def _is_number_or_empty(value: Any) -> bool:
    if value is None or type(value) is int:
        return True
    return type(value) is float and math.isfinite(value)


def _is_month(value: Any) -> bool:
    return isinstance(value, str) and MONTH_RE.fullmatch(value) is not None


def _no_repeats(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError('repeated key')
    return dict(pairs)


def _load_json(raw: bytes, check: int, name: str) -> Any:
    """Strict JSON: UTF-8, no repeated key in any object, no NaN or Infinity."""
    def no_constant(text: str) -> Any:
        raise ValueError('not a JSON number')
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=_no_repeats, parse_constant=no_constant)
    except (UnicodeDecodeError, ValueError):
        raise CheckFailed(check, f'{name} is not strict UTF-8 JSON (or repeats a key)') from None


def _attribution_ok(attribution: Any, year: str) -> bool:
    if not (isinstance(attribution, list) and len(attribution) == len(ATTRIBUTION_RES)):
        return False
    for statement, pattern in zip(attribution, ATTRIBUTION_RES):
        match = pattern.fullmatch(statement) if isinstance(statement, str) else None
        if match is None or any(found != year for found in match.groupdict().values()):
            return False
    return True


def check_table(state_raw: bytes, json_raw: bytes, csv_raw: bytes, live: dict[str, Any] | None,
                first_publish: bool) -> Table:
    """All eight checks of section 6, in order, plus the strictness of review C3. Raises CheckFailed (number and
    reason) at the first failure."""
    for name, raw in (('DT_STATE', state_raw), ('table_latest.json', json_raw), ('table_latest.csv', csv_raw)):
        if len(raw) > MAX_FILE_BYTES:
            raise CheckFailed(1, f'{name} is larger than {MAX_FILE_BYTES} bytes')
    state = _load_json(state_raw, 1, 'DT_STATE')
    document = _load_json(json_raw, 1, 'table_latest.json')
    if not isinstance(state, dict) or set(state) != STATE_KEYS:
        raise CheckFailed(1, 'DT_STATE does not have exactly its six keys')
    if not isinstance(document, dict) or set(document) != DOCUMENT_KEYS:
        raise CheckFailed(1, 'table_latest.json does not have exactly its keys')

    # 1. versions and columns
    if state['v'] != TABLE_VERSION or document['v'] != TABLE_VERSION or type(state['v']) is not int:
        raise CheckFailed(1, f'DT_STATE.v and the JSON v must both be {TABLE_VERSION}')
    if document['columns'] != list(COLUMNS):
        raise CheckFailed(1, 'the JSON columns are not the 16 names in order')

    # 2. the JSON and DT_STATE come from one build (and every field the page shows is checked here)
    month, built_at, rows = state['month'], state['builtAt'], state['rows']
    if not _is_month(month) or not (isinstance(built_at, str) and BUILT_AT_RE.fullmatch(built_at)):
        raise CheckFailed(2, 'DT_STATE month or builtAt is malformed')
    if not _is_count(rows) or not _is_count(state['districts']):
        raise CheckFailed(2, 'DT_STATE rows or districts is not a whole number')
    if not (isinstance(state['postcodeRelease'], str) and RELEASE_RE.fullmatch(state['postcodeRelease'])):
        raise CheckFailed(2, 'DT_STATE postcodeRelease is malformed')
    if (document['month'], document['builtAt'], document['postcodeRelease']) != (month, built_at, state['postcodeRelease']):
        raise CheckFailed(2, 'the JSON month, builtAt or postcodeRelease differs from DT_STATE')
    json_rows = document['rows']
    if not isinstance(json_rows, list) or len(json_rows) != rows:
        raise CheckFailed(2, 'the JSON row count differs from DT_STATE.rows')
    if document['title'] != TITLE or document['licence'] != LICENCE:
        raise CheckFailed(2, 'the JSON title or licence is not the expected one')
    if not all(_is_month(document[k]) for k in ('periodFrom', 'periodTo', 'previousPeriodFrom', 'previousPeriodTo', 'threeMonthFrom')):
        raise CheckFailed(2, 'a period bound in the JSON is not YYYY-MM')
    if not (document['periodFrom'] <= document['periodTo'] < month and document['previousPeriodTo'] < document['periodFrom']):
        raise CheckFailed(2, 'the period bounds are out of order')
    if document['lagMonths'] != LAG_MONTHS or type(document['lagMonths']) is not int:
        raise CheckFailed(2, f'lagMonths is not {LAG_MONTHS}')
    if not (isinstance(document['method'], str) and 0 < len(document['method']) <= MAX_METHOD_CHARS):
        raise CheckFailed(2, 'the method sentence is missing or too long')

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
        if not isinstance(row, dict) or set(row) != set(COLUMNS):
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
        if month < live['month'] or (month == live['month'] and built_at < live['builtAt']):
            raise CheckFailed(5, f'the table ({month}, built {built_at}) is older than the live one')
        # 6. the row count is within 20% of last month's
        if abs(rows - live['rows']) > ROW_CHANGE_LIMIT * live['rows']:
            raise CheckFailed(6, f'{rows} rows against {live["rows"]} live: more than a {ROW_CHANGE_LIMIT:.0%} change')

    # 7. every cell has the expected kind (and, beyond the spec, no postcode or sector can slip in)
    for index, row in enumerate(json_rows, start=1):
        if row['month'] != month or row['propertyType'] not in PROPERTY_TYPES:
            raise CheckFailed(7, f'row {index}: month or property type')
        if (row['periodFrom'], row['periodTo']) != (document['periodFrom'], document['periodTo']):
            raise CheckFailed(7, f'row {index}: the period differs from the table')
        if not (isinstance(row['district'], str) and DISTRICT_RE.fullmatch(row['district'])):
            raise CheckFailed(7, f'row {index}: the district is not an outcode')
        if not (isinstance(row['localAuthorityCodes'], str) and AUTHORITIES_RE.fullmatch(row['localAuthorityCodes'])):
            raise CheckFailed(7, f'row {index}: the authority codes')
        if not all(_is_count(row[c]) for c in COUNT_COLUMNS):
            raise CheckFailed(7, f'row {index}: a count is not a whole number')
        if not all(_is_number_or_empty(row[c]) for c in (*FIGURE_COLUMNS, 'medianChangePct')):
            raise CheckFailed(7, f'row {index}: a figure is not a number or empty')
        if type(row['lowSample']) is not bool:
            raise CheckFailed(7, f'row {index}: lowSample is not true or false')

    # 8. the attribution is present, word for word, with the build year (the page shows it: see plan_page)
    if not _attribution_ok(document['attribution'], built_at[:4]):
        raise CheckFailed(8, 'the two attribution statements are missing or not word for word')
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


def _region(text: str, name: str, content: str) -> str:
    start, end = f'<!-- district-table:{name} -->', f'<!-- /district-table:{name} -->'
    if text.count(start) != 1 or text.count(end) != 1 or text.index(start) > text.index(end):
        raise TemplateBroken(f'the page has no single {name} region')
    head, rest = text.split(start)
    _, tail = rest.split(end)
    return f'{head}{start}\n{content}{end}{tail}'


def render_regions(table: Table, sizes: dict[str, int]) -> dict[str, str]:
    """The three regions, from checked fields only, every value escaped. `sizes` maps each file name that will be
    served (after this publish) to its size in bytes."""
    d, e = table.document, html.escape
    summary = (f'<p>Latest table: {e(d["month"])}, sales from {e(d["periodFrom"])} to {e(d["periodTo"])}; '
               f'{table.rows:,} rows for {table.state["districts"]:,} districts. Built {e(d["builtAt"][:10])}.</p>\n')
    lines = ['<div class="table-wrap"><table><thead><tr><th>File</th><th>Month</th><th>Size</th></tr></thead>', '<tbody>']
    for ext in ('csv', 'json'):
        name = f'{LATEST}.{ext}'
        lines.append(f'<tr><td><a href="/data/sold-prices/{name}">{name}</a> (latest)</td><td>{e(d["month"])}</td><td>{_size(sizes[name])}</td></tr>')
    months = sorted({n[len('district-medians-'):-len('.json')] for n in sizes if n.endswith('.json') and n != f'{LATEST}.json'}, reverse=True)
    for month in months:
        for ext in ('csv', 'json'):
            name = f'district-medians-{month}.{ext}'
            lines.append(f'<tr><td><a href="/data/sold-prices/{name}">{name}</a></td><td>{e(month)}</td><td>{_size(sizes[name])}</td></tr>')
    lines.append('</tbody></table></div>')
    attribution = ''.join(f'<p class="attribution">{e(a)}</p>\n' for a in d['attribution'])
    return {'summary': summary, 'downloads': '\n'.join(lines) + '\n', 'attribution': attribution}


@dataclass(frozen=True)
class Plan:
    files: list[tuple[Path, bytes]]     # the data files to write, in order
    page: str
    sitemap: str
    done: list[str]


def plan_publish(root: Path, table: Table, today: str) -> Plan:
    """Everything the publish writes, worked out in memory. Raises CheckFailed or TemplateBroken before anything is
    written (review C2)."""
    out = root / OUT
    sizes: dict[str, int] = {}
    for path in out.glob('district-medians-*.*') if out.exists() else ():
        stem = path.name[len('district-medians-'):].rsplit('.', 1)[0]
        if path.suffix in ('.csv', '.json') and MONTH_RE.fullmatch(stem):
            sizes[path.name] = path.stat().st_size
    for month in {n[len('district-medians-'):].rsplit('.', 1)[0] for n in sizes}:
        if not {f'district-medians-{month}.csv', f'district-medians-{month}.json'} <= set(sizes):
            raise CheckFailed(5, f'the archive for {month} has only one of its two files', refused=True)
    files, done = [], []
    pair = [(f'district-medians-{table.month}.{ext}', data) for ext, data in (('json', table.json_bytes), ('csv', table.csv_bytes))]
    if all(name in sizes for name, _ in pair):
        if any((out / name).read_bytes() != data for name, data in pair):
            done.append(f'kept the {table.month} archive as first published (a later build of the month updates the latest files only)')
    else:
        for name, data in pair:
            files.append((out / name, data))
            sizes[name] = len(data)
            done.append(f'archived {name}')
    for name, data in ((f'{LATEST}.json', table.json_bytes), (f'{LATEST}.csv', table.csv_bytes)):
        files.append((out / name, data))
        sizes[name] = len(data)
        done.append(f'wrote {name}')
    try:
        page = (root / PAGE).read_text(encoding='utf-8')
        sitemap = (root / SITEMAP).read_text(encoding='utf-8')
    except OSError:
        raise TemplateBroken('the page or sitemap is missing') from None
    for name, content in render_regions(table, sizes).items():
        page = _region(page, name, content)
    for statement in table.document['attribution']:      # check 8: the attribution is shown on the page
        if f'<p class="attribution">{html.escape(statement)}</p>' not in page:
            raise CheckFailed(8, 'the attribution is not on the page')
    pattern = re.compile(r'(<loc>' + re.escape(PAGE_URL) + r'</loc>\s*<lastmod>)[0-9-]{10}(</lastmod>)')
    if len(pattern.findall(sitemap)) != 1:
        raise TemplateBroken('sitemap.xml has no single entry for the page')
    done.append('updated sold-prices/index.html and its sitemap lastmod')
    return Plan(files, page, pattern.sub(rf'\g<1>{today}\g<2>', sitemap), done)


def write_plan(root: Path, plan: Plan) -> None:
    (root / OUT).mkdir(parents=True, exist_ok=True)
    for path, data in plan.files:
        path.write_bytes(data)
    (root / PAGE).write_text(plan.page, encoding='utf-8', newline='\n')
    (root / SITEMAP).write_text(plan.sitemap, encoding='utf-8', newline='')


def is_this_repo(root: Path) -> bool:
    try:
        return (root / 'CNAME').read_text(encoding='utf-8').strip() == 'data.yappman.com'
    except OSError:
        return False


def main(argv: list[str] | None = None, *, root: Path = REPO, today: str | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='the checks only; writes nothing')
    mode.add_argument('--publish', action='store_true')
    parser.add_argument('--first-publish', action='store_true', help='only when no table is live yet')
    args = parser.parse_args(argv)
    if not is_this_repo(root):
        print(json.dumps({'status': 'refused', 'code': 'not-the-data-yappman-repo'}))
        return 2
    try:
        raws = [(root / INCOMING / name).read_bytes() for name in (STATE_FILE, JSON_FILE, CSV_FILE)]
    except OSError:
        print(json.dumps({'status': 'refused', 'code': 'incoming-files-missing', 'folder': str(INCOMING)}))
        return 2
    live = live_table(root)
    try:
        table = check_table(*raws, live, args.first_publish)
        if live is not None and live['month'] == table.month and live['builtAt'] == table.state['builtAt']:
            print(json.dumps({'status': 'nothing-new', 'month': table.month, 'builtAt': table.state['builtAt']}))
            return 0
        plan = plan_publish(root, table, today or datetime.now(UTC).date().isoformat())
    except CheckFailed as failure:
        print(json.dumps({'status': 'refused' if failure.refused else 'held', 'check': failure.check,
                          'reason': str(failure), 'live': live}))
        return 2 if failure.refused else 3
    except TemplateBroken as broken:
        print(json.dumps({'status': 'held', 'code': 'template-broken', 'reason': str(broken)}))
        return 3
    summary = {'month': table.month, 'builtAt': table.state['builtAt'], 'rows': table.rows, 'live': live}
    if args.check:
        print(json.dumps({'status': 'checks-passed', **summary, 'wouldDo': plan.done}))
        return 0
    write_plan(root, plan)
    print(json.dumps({'status': 'published', **summary, 'done': plan.done}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
