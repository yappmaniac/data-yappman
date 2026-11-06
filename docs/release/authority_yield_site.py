"""Gross rental yield by local authority, England and Wales: the website build (no network, no token).

Turns the three files that fetch_authority_yield.py saved (AY_STATE.json, yield_latest.json, yield_latest.csv) into
the download files and the page /rental-yield/. Run from anywhere (paths are anchored to this repo):

    python -I -B docs/release/authority_yield_site.py --check [--first-publish]     # the checks only, writes nothing
    python -I -B docs/release/authority_yield_site.py --publish [--first-publish]

Spec: Orchestrator drafts/sessions/property/authority-yield-review-and-promote-6-nov.md, section 3, and the Actor's
own writer (price_paid/src/authority_yield.py at 3e9ee16). It reuses the reviewed helpers of district_table_site.py
(strict JSON, cell matching, the in-memory plan, whole-file writes) and does not change that table or its files.
- Reads AY_STATE first and publishes only when every check passes; otherwise it writes nothing and what is live stays
  live (exit 3). The checks are section 3's list plus, as for the district table: no JSON object repeats a key; AY_STATE
  and the JSON top level have exact key sets with typed fields; title, licence, lagMonths, columns and the method
  sentence are pinned; the three attribution statements match word for word (only the year, the build year, varies);
  and every row is re-derived from its own rent, sales and median: the yield is rent x 12 / median to one decimal
  place, withheld on a type row exactly as the Actor's rule says (fewer than 20 sales, or under half the authority's
  all-homes yield), with one of the two pinned reasons, so the page cannot show a figure the rule would withhold.
- Writes data/rental-yield/rental-yield-latest.{csv,json} and, once per month and PIPR edition, the dated archive
  rental-yield-<YYYY-MM>-pipr-<YYYY-MM-DD>.{csv,json}. An archive file is never rewritten.
- Rewrites only the marked parts of rental-yield/index.html (summary, downloads, method, attribution, every row) and
  the page's lastmod in sitemap.xml. The files are published as fetched (byte for byte).

Exit codes: 0 published, or nothing new; 2 refused (usage, wrong folder, or --first-publish against a live table);
3 a check failed or the page template is broken, nothing written.
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import district_table_site as dts  # noqa: E402  (the reviewed helpers; nothing in it is changed)

CheckFailed, TemplateBroken = dts.CheckFailed, dts.TemplateBroken

AY_VERSION = 2
LAG_MONTHS = 3
TITLE = 'Gross rental yield by local authority, England and Wales'
LICENCE = 'Open Government Licence v3.0'
COLUMNS = (
    'month', 'periodFrom', 'periodTo', 'piprEdition', 'authorityCode', 'authorityName', 'country', 'propertyType',
    'rentMonthly', 'sales12m', 'medianPrice12m', 'grossYieldPct', 'yieldWithheld', 'lowSample',
    'rentOneBed', 'rentTwoBed', 'rentThreeBed', 'rentFourPlusBed',
)
BEDROOM_COLUMNS = ('rentOneBed', 'rentTwoBed', 'rentThreeBed', 'rentFourPlusBed')
DOCUMENT_KEYS = frozenset({'v', 'title', 'month', 'periodFrom', 'periodTo', 'lagMonths', 'piprEdition', 'builtAt',
                           'licence', 'attribution', 'method', 'columns', 'rows'})
STATE_KEYS = frozenset({'v', 'month', 'piprEdition', 'builtAt', 'authorities', 'rows'})
PROPERTY_TYPES = ('all', 'detached', 'semi-detached', 'terraced', 'flat')     # the Actor writes all five, in this order
MIN_SALES = 5
LOW_SAMPLE_BELOW = 20
WITHHOLD_BELOW_SALES = 20
WITHHOLD_BELOW_SHARE_OF_ALL = Decimal('0.5')
WITHHELD_FEW_SALES = f'fewer than {WITHHOLD_BELOW_SALES} sales of this type'
WITHHELD_NOT_ALIKE = "this type's rents and sales do not describe like homes here (yield under half the all-homes figure)"
REASONS = (WITHHELD_FEW_SALES, WITHHELD_NOT_ALIKE)
# The Actor's METHOD, word for word (authority_yield.py at 3e9ee16, MIN_SALES 5, LOW_SAMPLE_BELOW 20,
# WITHHOLD_BELOW_SALES 20). Pinned: if the Actor's wording changes, the table is held until this matches.
METHOD = (
    'Gross yield is the average monthly rent times 12, divided by the median price, as a percentage to one decimal place. '
    'The rent is the mean of the 12 monthly figures of the ONS Price Index of Private Rents (PIPR, ONS statistics in '
    'development), an average of rents on new and existing tenancies, for the same 12 months as the sales, in whole pounds; '
    'it is null unless all 12 months are available, and PIPR is not seasonally adjusted. The price is the median of '
    'HM Land Registry category A (standard price paid) sales over those 12 months, null when there are fewer than '
    '5 sales (a quality threshold: every sale is already published by HM Land Registry); lowSample is true '
    'under 20 sales. On a property-type row the yield is withheld, with the reason in yieldWithheld, when the type '
    "has fewer than 20 sales or when it is below half of the authority's all-homes yield (taken as a sign "
    'that the rented and the sold homes of the type are not alike); the rent, sales and median are still given. The yield is gross, '
    'before costs, voids, tax and finance. The rent is a mean and the '
    'price a median, and the mix of homes differs, so these are area averages, not a valuation and not advice. Bedroom '
    'rents are context on the all row only: HM Land Registry has no bedroom counts. England and Wales local authorities '
    'only: Scotland and Northern Ireland are not covered (PIPR publishes them by Broad Rental Market Area, and HM Land '
    'Registry has no data for them), nor are authorities PIPR does not publish (City of London and the Isles of Scilly).'
)
ATTRIBUTION_RES = (
    re.compile(r'Contains HM Land Registry data © Crown copyright and database right (?P<a>20[0-9]{2})\. '
               r'This data is licensed under the Open Government Licence v3\.0\.'),
    re.compile(r'Source: Office for National Statistics licensed under the Open Government Licence v3\.0\.'),
    re.compile(r'Contains OS data © Crown copyright and database right (?P<a>20[0-9]{2})\. '
               r'Contains Royal Mail data © Royal Mail copyright and database right (?P<b>20[0-9]{2})\.'),
)
EDITION_RE = re.compile(r'20[0-9]{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])')
AUTHORITY_RE = re.compile(r'[EW]0[6-9][0-9]{6}')      # E06-E09 and W06: unitary, district, metropolitan, London, Welsh
# letters only (Welsh names included) and a few separators: no digit, so no postcode, and no markup (review 1)
NAME_RE = re.compile(r"[^\W\d_](?:[^\W\d_]|[ ,.'’&()/-]){1,79}")
MAX_RENT = 100_000            # a monthly rent above this is a parsing fault, not a rent
MAX_PRICE = 100_000_000
MAX_SALES = 1_000_000         # more 12-month sales than this in one authority is a fault (review 6)
CLOCK_SKEW_SECONDS = 3600     # a builtAt this far ahead of our clock is refused (review 6)
# England and Wales local authorities in PIPR: 316 on 6 Nov 2026 (294 English, 22 Welsh). A table far outside this
# is a fault, not a reorganisation (Orchestrator review W-a). Tests narrow these to their fixtures.
MIN_AUTHORITIES = 300
MAX_AUTHORITIES = 330

INCOMING = Path('_incoming/rental-yield')
OUT = Path('data/rental-yield')
PAGE = Path('rental-yield/index.html')
PAGE_URL = 'https://data.yappman.com/rental-yield/'
STATE_FILE, JSON_FILE, CSV_FILE = 'AY_STATE.json', 'yield_latest.json', 'yield_latest.csv'
LATEST = 'rental-yield-latest'
ARCHIVE_RE = re.compile(r'rental-yield-(?P<month>[0-9]{4}-(?:0[1-9]|1[0-2]))-pipr-(?P<edition>' + EDITION_RE.pattern + r')\.(?:csv|json)')


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
    def edition(self) -> str:
        return self.state['piprEdition']

    @property
    def rows(self) -> int:
        return self.state['rows']

    @property
    def archive(self) -> str:
        return f'rental-yield-{self.month}-pipr-{self.edition}'


def gross_yield_pct(rent: int | None, median: int | None) -> float | None:
    """The Actor's formula: rent x 12 / median x 100, one decimal place, half up, in Decimal; None unless both exist."""
    if rent is None or median is None or median <= 0:
        return None
    return float((Decimal(rent) * 12 / Decimal(median) * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))


def expected_yield(row: dict[str, Any], all_yield: float | None) -> tuple[float | None, str | None]:
    """What the Actor's rule gives for this row: (grossYieldPct, yieldWithheld)."""
    computed = gross_yield_pct(row['rentMonthly'], row['medianPrice12m'])
    if row['propertyType'] == 'all' or computed is None:
        return computed, None
    if row['sales12m'] < WITHHOLD_BELOW_SALES:
        return None, WITHHELD_FEW_SALES
    if all_yield is not None and Decimal(str(computed)) < Decimal(str(all_yield)) * WITHHOLD_BELOW_SHARE_OF_ALL:
        return None, WITHHELD_NOT_ALIKE
    return computed, None


def _attribution_ok(attribution: Any, year: str) -> bool:
    if not (isinstance(attribution, list) and len(attribution) == len(ATTRIBUTION_RES)):
        return False
    for statement, pattern in zip(attribution, ATTRIBUTION_RES):
        match = pattern.fullmatch(statement) if isinstance(statement, str) else None
        if match is None or any(found != year for found in match.groupdict().values()):
            return False
    return True


def _is_amount(value: Any, ceiling: int) -> bool:
    return value is None or (type(value) is int and 0 < value <= ceiling)


def _month_minus(month: str, months: int) -> str:
    index = int(month[:4]) * 12 + int(month[5:7]) - 1 - months
    return f'{index // 12:04d}-{index % 12 + 1:02d}'


def check_table(state_raw: bytes, json_raw: bytes, csv_raw: bytes, live: dict[str, Any] | None,
                first_publish: bool, now: datetime | None = None) -> Table:
    """Every check, in order. Raises CheckFailed (number and reason) at the first failure. `now` is for the tests."""
    now = now or datetime.now(UTC)
    for name, raw in (('AY_STATE', state_raw), ('yield_latest.json', json_raw), ('yield_latest.csv', csv_raw)):
        if len(raw) > dts.MAX_FILE_BYTES:
            raise CheckFailed(1, f'{name} is larger than {dts.MAX_FILE_BYTES} bytes')
    state = dts._load_json(state_raw, 1, 'AY_STATE')
    document = dts._load_json(json_raw, 1, 'yield_latest.json')
    if not isinstance(state, dict) or set(state) != STATE_KEYS:
        raise CheckFailed(1, 'AY_STATE does not have exactly its six keys')
    if not isinstance(document, dict) or set(document) != DOCUMENT_KEYS:
        raise CheckFailed(1, 'yield_latest.json does not have exactly its keys')

    # 1. versions and columns
    if state['v'] != AY_VERSION or document['v'] != AY_VERSION or type(state['v']) is not int or type(document['v']) is not int:
        raise CheckFailed(1, f'AY_STATE.v and the JSON v must both be {AY_VERSION}')
    if document['columns'] != list(COLUMNS):
        raise CheckFailed(1, 'the JSON columns are not the 18 names in order')

    # 2. the JSON and AY_STATE come from one build; every field the page shows is checked here
    month, edition, built_at, rows = state['month'], state['piprEdition'], state['builtAt'], state['rows']
    if not dts._is_month(month) or not (isinstance(edition, str) and EDITION_RE.fullmatch(edition)):
        raise CheckFailed(2, 'AY_STATE month or piprEdition is malformed')
    if not (isinstance(built_at, str) and dts.BUILT_AT_RE.fullmatch(built_at)):
        raise CheckFailed(2, 'AY_STATE builtAt is malformed')
    try:
        ahead = (dts._instant(built_at) - now).total_seconds()
    except ValueError:
        raise CheckFailed(2, 'AY_STATE builtAt is not a real time') from None
    if month > now.strftime('%Y-%m') or ahead > CLOCK_SKEW_SECONDS:
        raise CheckFailed(2, 'AY_STATE month or builtAt is in the future')
    if not dts._is_count(rows) or not dts._is_count(state['authorities']) or rows != 5 * state['authorities']:
        raise CheckFailed(2, 'AY_STATE rows is not five times its authorities')
    if not MIN_AUTHORITIES <= state['authorities'] <= MAX_AUTHORITIES:
        raise CheckFailed(2, f'{state["authorities"]} authorities, outside {MIN_AUTHORITIES} to {MAX_AUTHORITIES}')
    if (document['month'], document['piprEdition'], document['builtAt']) != (month, edition, built_at):
        raise CheckFailed(2, 'the JSON month, piprEdition or builtAt differs from AY_STATE')
    json_rows = document['rows']
    if not isinstance(json_rows, list) or len(json_rows) != rows:
        raise CheckFailed(2, 'the JSON row count differs from AY_STATE.rows')
    if document['title'] != TITLE or document['licence'] != LICENCE:
        raise CheckFailed(2, 'the JSON title or licence is not the expected one')
    # the page says the 12 months end three months before month (review 5): exactly that
    if (document['periodTo'], document['periodFrom']) != (_month_minus(month, LAG_MONTHS), _month_minus(month, LAG_MONTHS + 11)):
        raise CheckFailed(2, 'the period is not the 12 months ending three months before month')
    if document['lagMonths'] != LAG_MONTHS or type(document['lagMonths']) is not int:
        raise CheckFailed(2, f'lagMonths is not {LAG_MONTHS}')
    if document['method'] != METHOD:
        raise CheckFailed(2, 'the method sentence is not the expected one')

    # 3. the CSV is the same build, cell for cell
    try:
        csv_text = csv_raw.decode('utf-8')
        parsed = list(csv.reader(io.StringIO(csv_text, newline='')))
    except (UnicodeDecodeError, csv.Error):
        raise CheckFailed(3, 'yield_latest.csv is not UTF-8 CSV') from None
    if not parsed or parsed[0] != list(COLUMNS):
        raise CheckFailed(3, 'the CSV header is not the columns')
    body = parsed[1:]
    if len(body) != rows:
        raise CheckFailed(3, 'the CSV row count differs from AY_STATE.rows')
    for index, (cells, row) in enumerate(zip(body, json_rows), start=1):
        if not isinstance(row, dict) or len(row) != len(COLUMNS) or set(row) != set(COLUMNS):
            raise CheckFailed(3, f'JSON row {index} does not have the 18 keys')
        if len(cells) != len(COLUMNS) or not all(dts.cell_matches(cell, row[c]) for cell, c in zip(cells, COLUMNS)):
            raise CheckFailed(3, f'CSV row {index} differs from JSON row {index}')

    # 5. not older than what is live; a first publish only when nothing is live
    if live is None:
        if not first_publish:
            raise CheckFailed(5, 'nothing is live: run with --first-publish for the first table', refused=True)
    else:
        if first_publish:
            raise CheckFailed(5, '--first-publish refused: a table is already live', refused=True)
        if (month, edition) < (live['month'], live['piprEdition']) or (
                (month, edition) == (live['month'], live['piprEdition']) and dts._instant(built_at) < dts._instant(live['builtAt'])):
            raise CheckFailed(5, f'the table ({month}, PIPR {edition}, built {built_at}) is older than the live one')
        # 6. the row count is within 20% of last month's
        if abs(rows - live['rows']) > dts.ROW_CHANGE_LIMIT * live['rows']:
            raise CheckFailed(6, f'{rows} rows against {live["rows"]} live: more than a {dts.ROW_CHANGE_LIMIT:.0%} change')

    # 7. every row: kinds, the five types per authority in order, and the figures re-derived from the row itself
    seen: set[str] = set()
    for start in range(0, rows, 5):
        group = json_rows[start:start + 5]
        code = group[0]['authorityCode']
        if not (isinstance(code, str) and AUTHORITY_RE.fullmatch(code)) or code in seen:
            raise CheckFailed(7, f'row {start + 1}: the authority code is malformed or repeated')
        seen.add(code)
        if [r['propertyType'] for r in group] != list(PROPERTY_TYPES):
            raise CheckFailed(7, f'{code}: the five property types are not in order')
        all_yield = group[0]['grossYieldPct']
        for offset, row in enumerate(group):
            where = f'row {start + offset + 1} ({code} {row["propertyType"]})'
            if (row['month'], row['periodFrom'], row['periodTo'], row['piprEdition']) != (
                    month, document['periodFrom'], document['periodTo'], edition):
                raise CheckFailed(7, f'{where}: the month, period or edition differs from the table')
            name = row['authorityName']
            if row['authorityCode'] != code or not (isinstance(name, str) and NAME_RE.fullmatch(name)) \
                    or any(c.isnumeric() for c in name):
                raise CheckFailed(7, f'{where}: the authority code or name')
            if row['authorityName'] != group[0]['authorityName'] or row['country'] != ('England' if code[0] == 'E' else 'Wales'):
                raise CheckFailed(7, f'{where}: the name or country differs within the authority')
            # W-a: an authority already published keeps its published name; a renamed or swapped name is held for a
            # person to look at (a new code, after a reorganisation, is allowed)
            if live is not None and code in live['names'] and live['names'][code] != row['authorityName']:
                raise CheckFailed(7, f'{where}: the name differs from the live table\'s name for {code}')
            if not dts._is_count(row['sales12m']) or row['sales12m'] > MAX_SALES or not _is_amount(row['rentMonthly'], MAX_RENT) \
                    or not _is_amount(row['medianPrice12m'], MAX_PRICE):
                raise CheckFailed(7, f'{where}: a count, rent or price is not a whole number in range')
            if (row['medianPrice12m'] is None) != (row['sales12m'] < MIN_SALES):
                raise CheckFailed(7, f'{where}: the median is blank or shown against its sales count')
            if row['lowSample'] is not (row['sales12m'] < LOW_SAMPLE_BELOW):
                raise CheckFailed(7, f'{where}: lowSample does not match sales12m')
            if not dts._is_number_or_empty(row['grossYieldPct']) or row['yieldWithheld'] not in (None, *REASONS):
                raise CheckFailed(7, f'{where}: the yield or the withheld reason')
            if (row['grossYieldPct'], row['yieldWithheld']) != expected_yield(row, all_yield):
                raise CheckFailed(7, f'{where}: the yield is not what the rule gives from the row\'s rent, sales and median')
            for column in BEDROOM_COLUMNS:
                if not _is_amount(row[column], MAX_RENT) or (row['propertyType'] != 'all' and row[column] is not None):
                    raise CheckFailed(7, f'{where}: a bedroom rent off the all row, or out of range')

    # 8. the three attribution statements, word for word, with the build year (the page shows them: see plan_publish)
    if not _attribution_ok(document['attribution'], built_at[:4]):
        raise CheckFailed(8, 'the three attribution statements are missing or not word for word')
    return Table(state, document, json_raw, csv_raw)


def live_table(root: Path) -> dict[str, Any] | None:
    path = root / OUT / f'{LATEST}.json'
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_bytes().decode('utf-8'))
        live = {k: document[k] for k in ('month', 'piprEdition', 'builtAt')} | {'rows': len(document['rows'])}
        live['names'] = {row['authorityCode']: row['authorityName'] for row in document['rows']}
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        raise CheckFailed(5, 'the live latest file cannot be read') from None
    if not (dts._is_month(live['month']) and isinstance(live['piprEdition'], str) and EDITION_RE.fullmatch(live['piprEdition'])
            and isinstance(live['builtAt'], str) and dts.BUILT_AT_RE.fullmatch(live['builtAt'])):
        raise CheckFailed(5, 'the live latest file has a malformed month, edition or builtAt (edited by hand?)')
    return live


def _pounds(value: int | None) -> str:
    return '&ndash;' if value is None else f'&pound;{value:,}'


def render_regions(table: Table, sizes: dict[str, int]) -> dict[str, str]:
    """The five regions, from checked fields only, every text value escaped."""
    d, e = table.document, html.escape
    with_yield = sum(1 for r in d['rows'] if r['grossYieldPct'] is not None)
    withheld = sum(1 for r in d['rows'] if r['yieldWithheld'] is not None)
    summary = (f'<p>Latest table: {e(d["month"])}, rents and sales from {e(d["periodFrom"])} to {e(d["periodTo"])}, '
               f'PIPR edition of {e(d["piprEdition"])}; {table.state["authorities"]:,} local authorities, {table.rows:,} rows, '
               f'{with_yield:,} with a yield and {withheld:,} type yields withheld. Built {e(d["builtAt"][:10])}.</p>\n')
    lines = ['<div class="table-wrap"><table><thead><tr><th>File</th><th>Month</th><th>PIPR edition</th><th>Size</th></tr></thead>', '<tbody>']
    for ext in ('csv', 'json'):
        name = f'{LATEST}.{ext}'
        lines.append(f'<tr><td><a href="/data/rental-yield/{name}">{name}</a> (latest)</td><td>{e(d["month"])}</td>'
                     f'<td>{e(d["piprEdition"])}</td><td>{dts._size(sizes[name])}</td></tr>')
    archives = sorted({ARCHIVE_RE.fullmatch(n).group('month', 'edition') for n in sizes if ARCHIVE_RE.fullmatch(n)}, reverse=True)
    for month, edition in archives:
        for ext in ('csv', 'json'):
            name = f'rental-yield-{month}-pipr-{edition}.{ext}'
            lines.append(f'<tr><td><a href="/data/rental-yield/{name}">{name}</a></td><td>{e(month)}</td><td>{e(edition)}</td>'
                         f'<td>{dts._size(sizes[name])}</td></tr>')
    lines.append('</tbody></table></div>')
    attribution = ''.join(f'<p class="attribution">{e(a)}</p>\n' for a in d['attribution'])
    method = f'<p class="method">{e(d["method"])}</p>\n'
    notes = {WITHHELD_FEW_SALES: 'note-few', WITHHELD_NOT_ALIKE: 'note-unlike'}
    marks = {WITHHELD_FEW_SALES: '1', WITHHELD_NOT_ALIKE: '2'}
    body = ['<div class="table-wrap"><table><thead><tr><th>Local authority</th><th>Country</th><th>Type</th>'
            '<th>Monthly rent</th><th>Sales (12 months)</th><th>Median price</th><th>Gross yield</th></tr></thead>', '<tbody>']
    ordered = sorted(range(0, table.rows, 5), key=lambda i: (d['rows'][i]['authorityName'].lower(), d['rows'][i]['authorityCode']))
    for start in ordered:
        for row in d['rows'][start:start + 5]:
            if row['grossYieldPct'] is not None:
                shown = f'{row["grossYieldPct"]:.1f}%'
            elif row['yieldWithheld'] is not None:
                reason = row['yieldWithheld']
                shown = f'&ndash;<sup><a href="#{notes[reason]}">{marks[reason]}</a></sup>'
            else:
                shown = '&ndash;'
            body.append(f'<tr><td>{e(row["authorityName"])} ({e(row["authorityCode"])})</td><td>{e(row["country"])}</td>'
                        f'<td>{e(row["propertyType"])}</td><td>{_pounds(row["rentMonthly"])}</td><td>{row["sales12m"]:,}</td>'
                        f'<td>{_pounds(row["medianPrice12m"])}</td><td>{shown}</td></tr>')
    body.append('</tbody></table></div>')
    body.append(f'<p class="note" id="note-few"><sup>1</sup> Yield withheld: {e(WITHHELD_FEW_SALES)}.</p>')
    body.append(f'<p class="note" id="note-unlike"><sup>2</sup> Yield withheld: {e(WITHHELD_NOT_ALIKE)}.</p>')
    return {'summary': summary, 'downloads': '\n'.join(lines) + '\n', 'attribution': attribution, 'method': method,
            'rows': '\n'.join(body) + '\n'}


@dataclass(frozen=True)
class Plan:
    files: list[tuple[Path, bytes]]
    page: str
    sitemap: str
    done: list[str]


def plan_publish(root: Path, table: Table, today: str) -> Plan:
    """Everything the publish writes, worked out in memory; raises before anything is written."""
    out = root / OUT
    sizes: dict[str, int] = {}
    for path in out.glob('rental-yield-*.*') if out.exists() else ():
        if ARCHIVE_RE.fullmatch(path.name):
            sizes[path.name] = path.stat().st_size
    for stem in {n.rsplit('.', 1)[0] for n in sizes}:
        if not {f'{stem}.csv', f'{stem}.json'} <= set(sizes):
            raise CheckFailed(5, f'the archive {stem} has only one of its two files', refused=True)
    files, done = [], []
    pair = [(f'{table.archive}.{ext}', data) for ext, data in (('json', table.json_bytes), ('csv', table.csv_bytes))]
    if all(name in sizes for name, _ in pair):
        if any((out / name).read_bytes() != data for name, data in pair):
            done.append(f'kept the {table.archive} archive as first published (the latest files are updated)')
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
        sitemap = (root / dts.SITEMAP).read_text(encoding='utf-8')
    except OSError:
        raise TemplateBroken('the page or sitemap is missing') from None
    for name, content in render_regions(table, sizes).items():
        page = dts._region(page, name, content)
    for statement in table.document['attribution']:      # check 8: the attribution is shown on the page
        if f'<p class="attribution">{html.escape(statement)}</p>' not in page:
            raise CheckFailed(8, 'the attribution is not on the page')
    if f'<p class="method">{html.escape(METHOD)}</p>' not in page:
        raise CheckFailed(8, 'the method is not on the page')
    pattern = re.compile(r'(<loc>' + re.escape(PAGE_URL) + r'</loc>\s*<lastmod>)[0-9-]{10}(</lastmod>)')
    if len(pattern.findall(sitemap)) != 1:
        raise TemplateBroken('sitemap.xml has no single entry for the page')
    done.append('updated rental-yield/index.html and its sitemap lastmod')
    return Plan(files, page, pattern.sub(rf'\g<1>{today}\g<2>', sitemap), done)


def write_plan(root: Path, plan: Plan) -> None:
    (root / OUT).mkdir(parents=True, exist_ok=True)
    for path, data in plan.files:
        dts._replace(path, data)
    dts._replace(root / PAGE, plan.page.encode('utf-8'))
    dts._replace(root / dts.SITEMAP, plan.sitemap.encode('utf-8'))


def main(argv: list[str] | None = None, *, root: Path = dts.REPO, today: str | None = None,
         now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='the checks only; writes nothing')
    mode.add_argument('--publish', action='store_true')
    parser.add_argument('--first-publish', action='store_true', help='only when no table is live yet')
    args = parser.parse_args(argv)
    if not dts.is_this_repo(root):
        print(json.dumps({'status': 'refused', 'code': 'not-the-data-yappman-repo'}))
        return 2
    try:
        raws = [(root / INCOMING / name).read_bytes() for name in (STATE_FILE, JSON_FILE, CSV_FILE)]
    except OSError:
        print(json.dumps({'status': 'refused', 'code': 'incoming-files-missing', 'folder': str(INCOMING)}))
        return 2
    live = None
    try:
        live = live_table(root)
        table = check_table(*raws, live, args.first_publish, now)
        if live is not None and (live['month'], live['piprEdition'], live['builtAt']) == (table.month, table.edition, table.state['builtAt']):
            print(json.dumps({'status': 'nothing-new', 'month': table.month, 'piprEdition': table.edition}))
            return 0
        plan = plan_publish(root, table, today or datetime.now(UTC).date().isoformat())
    except CheckFailed as failure:
        print(json.dumps({'status': 'refused' if failure.refused else 'held', 'check': failure.check,
                          'reason': str(failure), 'live': live}))
        return 2 if failure.refused else 3
    except TemplateBroken as broken:
        print(json.dumps({'status': 'held', 'code': 'template-broken', 'reason': str(broken)}))
        return 3
    summary = {'month': table.month, 'piprEdition': table.edition, 'builtAt': table.state['builtAt'], 'rows': table.rows, 'live': live}
    if args.check:
        print(json.dumps({'status': 'checks-passed', **summary, 'wouldDo': plan.done}))
        return 0
    write_plan(root, plan)
    print(json.dumps({'status': 'published', **summary, 'done': plan.done}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
