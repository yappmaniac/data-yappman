"""Median sold prices by local authority and region, by year and quarter (area history): the website build (no network, no token).

Turns the files saved in _incoming/sold-prices-area-history/ (AH_STATE.json, ah_index.json and, for each entry of the
index's `files` list, <key>.json and <key>.csv) into the download files and the page /sold-prices/history/areas/. Run
from anywhere (paths are anchored to this repo):

    python -I -B docs/release/area_history_site.py --check [--from DIR]                    # the checks only, writes nothing
    python -I -B docs/release/area_history_site.py --publish [--first-publish] [--from DIR]

Source and checks: Orchestrator drafts/sessions/property/area-history-gates-20-nov.md, gate 4, and the Actor's own format
(price_paid/src/area_history.py, AREA_VERSION 1). The postcode-district history (/sold-prices/history/, its files and
docs/release/history_table_site.py) and the monthly table are NOT touched; this module only imports the monthly build's
reviewed helpers.

What it does:
- Unknown EXTRA fields in the state, the index (and its entries and totals) and each file's document are ignored (the Actor may add fields,
  for example an incremental build's buildKind or yearDigests); every required key is still checked, and rows stay exact (eleven fields).
- Reads the saved files and publishes only when every check passes; otherwise it writes nothing and what is live stays live
  (exit 3). Only the files the index lists are used (an older file left in the folder is ignored). Checks:
    versions all 1 (state, index, every file); month, lastYear, lastQuarter, postcodeRelease and builtAt equal in AH_STATE,
    the index and EVERY file; regionLookupSha256 is 64 hex characters; each file's row count equals its index entry, the
    entries sum to totals.rows and AH_STATE.rows, and the file count equals totals.files; the key set and kind of every
    file (three files for each of the ten regions, and ah_regions); the CSV header equals the columns and the CSV rows
    equal the JSON rows; periodType, period range, geography, authority and region codes, the split set for each period
    type; sales at least 1, figures empty exactly when sales is under 5, lowSample true exactly when sales is under 20;
    each region row's sales equal the sum of its authorities' sales for the same period and split; the licence, the
    method, the title and the three attribution statements exactly as expected (so what is checked is what is shown).
- Plans everything in memory first (the page, the sitemap and llms.txt included) and writes only when the plan is complete.
- Ships, per build: ah_index.json, ah_regions.json and .csv, each region's yearly .json and .csv, and each region's
  quarterly files as CSV ONLY (the quarterly JSON files are checked and not shipped: the page reads the CSV for quarters).
  They go to data/sold-prices/area-history/<month>/ (the dated archive of that build, written once and never rewritten)
  and the latest build's index to data/sold-prices/area-history/index.json (the page reads it to find the newest folder).
  A month whose folder exists and differs is held (exit 3): an archive is never rewritten, so a person decides.
- Retention (approved by Russell): keep the latest vintage plus ONE year-end vintage (a build whose last quarter is the
  fourth quarter of its last year) in the tree, no more. This build never deletes: it prints which dated folders break
  the rule (`retention.remove`) and a person removes them.
- Rewrites only the marked parts of sold-prices/history/areas/index.html (summary, downloads, archive, attribution, method
  and the unassigned-sales line, taken from the checked JSON and escaped), that page's entry in sitemap.xml (added on the
  first publish, lastmod afterwards) and its line in llms.txt (first publish). The files are published as fetched (byte for byte).

Exit codes: 0 published, or nothing new; 2 refused (usage, wrong folder, files missing, or --first-publish against a live
history); 3 a check failed or the page template is broken, nothing written.
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from district_table_site import (  # noqa: E402  (the reviewed helpers of the monthly table's build, unchanged)
    ATTRIBUTION_RES, BUILT_AT_RE, LICENCE, LOW_SAMPLE_BELOW, MAX_FILE_BYTES, MIN_SALES, RELEASE_RE, CheckFailed, TemplateBroken,
    _instant, _is_count, _is_month, _is_number_or_empty, _load_json, _replace, _size, cell_matches, is_this_repo,
)

AREA_VERSION = 1
TITLE = 'Median sold prices by local authority and region, England and Wales'
FIRST_YEAR = 1995
COLUMNS = ('periodType', 'period', 'geography', 'code', 'name', 'split', 'sales', 'median', 'lowerQuartile', 'upperQuartile', 'lowSample')
YEAR_SPLITS = ('all', 'detached', 'semi-detached', 'terraced', 'flat', 'freehold', 'leasehold', 'new-build', 'existing')
QUARTER_SPLITS = ('all', 'detached', 'semi-detached', 'terraced', 'flat')
STATE_KEYS = frozenset({'v', 'month', 'lastYear', 'lastQuarter', 'postcodeRelease', 'regionLookupSha256', 'builtAt', 'authorities',
                        'regions', 'files', 'rows'})
INDEX_KEYS = frozenset({'v', 'title', 'firstYear', 'lastYear', 'lastQuarter', 'month', 'postcodeRelease', 'builtAt', 'licence',
                        'attribution', 'method', 'columns', 'files', 'totals'})
FILE_KEYS = frozenset({'v', 'title', 'area', 'kind', 'block', 'firstYear', 'lastYear', 'lastQuarter', 'month', 'postcodeRelease',
                       'builtAt', 'licence', 'attribution', 'method', 'columns', 'rows'})
ENTRY_KEYS = frozenset({'key', 'region', 'regionName', 'kind', 'block', 'rows', 'authorities'})
TOTALS_KEYS = frozenset({'authorities', 'regions', 'files', 'rows', 'suppressed', 'unassignedSales'})
BLOCKS = (('1995-2009', 1995, 2009), ('2010-onwards', 2010, None))
REGIONS_BASE = 'ah_regions'
MAX_FILES = 100                      # the Actor's own refusal; a later split of the quarterly block adds files
FIGURE_COLUMNS = ('median', 'lowerQuartile', 'upperQuartile')
REGION_CODES = frozenset([f'E1200000{n}' for n in range(1, 10)] + ['W92000004'])
WALES_CODE = 'W92000004'
LOOKUP_SHA_RE = re.compile(r'[0-9a-f]{64}')
LAST_QUARTER_RE = re.compile(r'(?P<y>[0-9]{4})-Q(?P<q>[1-4])')
PERIOD_QUARTER_RE = LAST_QUARTER_RE
KEY_RE = re.compile(r'ah_(?:regions|(?P<r>E1200000[1-9]|W92000004)_(?:year|qtr_(?:1995-2009|2010-onwards)))')
AUTHORITY_CODE_RE = re.compile(r'(?:E0[6-9]|W06)[0-9]{6}')
# The same name rule the Actor applies before it writes a name (price_paid/src/area_history.py _AUTHORITY_NAME).
NAME_RE = re.compile(r"[^\W_](?:[^\W_]|[ ,.'’&()\-]){0,99}")
# The Actor's wording, word for word (area_history.py METHOD, REGION_ATTRIBUTION, MIN_SALES 5). Pinned so no other free text
# reaches the public files; if the Actor's wording changes, the build is held until this matches.
REGION_ATTRIBUTION = 'Region lookup: Source: Office for National Statistics licensed under the Open Government Licence v.3.0.'
METHOD = (
    'Category A (standard price paid) sales only, by transfer date, one row per local authority or region, period '
    '(calendar year or calendar quarter) and split (a split is one grouping at a time: all sales, one property type, '
    'one tenure, or new-build or existing; they are not combined; quarters have all sales and the four property types '
    'only). Medians and quartiles (inclusive method) in whole pounds, nominal and not adjusted for inflation; null '
    'when a period has fewer than 5 sales (a quality threshold: every sale is already published by HM Land '
    'Registry). Rows with no sales are left out. Only complete periods are shown; the latest period is as at the month '
    'the file was built, and sales registered later are added when the file is next rebuilt (when a new quarter has '
    'ended or the postcode release changes). Authorities are the current authorities of the ONS Postcode Directory '
    'release named in the file, applied back to 1995: a sale counts in the authority its postcode is in today, not '
    'the authority it was in at the time. Sales whose postcode could not be placed in an authority are counted in no '
    'area. Regions are the English regions of the ONS lookup; Wales is one area. England and Wales only. Not an '
    'index: the mix of homes sold changes from period to period.'
)
# The incremental build (Property, price_paid area_history.py on branch price-paid-area-incremental, 20 Nov 2026) states that
# periods more than two years old are as at the last full rebuild. Both sentences are the Actor's own; either is accepted, and
# every file of one build must carry the same one as its index.
METHOD_INCREMENTAL = (
    'Category A (standard price paid) sales only, by transfer date, one row per local authority or region, period '
    '(calendar year or calendar quarter) and split (a split is one grouping at a time: all sales, one property type, '
    'one tenure, or new-build or existing; they are not combined; quarters have all sales and the four property types '
    'only). Medians and quartiles (inclusive method) in whole pounds, nominal and not adjusted for inflation; null '
    'when a period has fewer than 5 sales (a quality threshold: every sale is already published by HM Land '
    'Registry). Rows with no sales are left out. Only complete periods are shown. The latest periods are as at the '
    'month the file was built, and sales registered later are added when the file is next rebuilt (when a new quarter '
    'has ended or the postcode release changes). Periods more than two years old are as at the last full rebuild of '
    'the file (lastFullBuildAt in the index); the newer periods are read again at every build. Authorities are the current authorities of the ONS Postcode Directory '
    'release named in the file, applied back to 1995: a sale counts in the authority its postcode is in today, not '
    'the authority it was in at the time. Sales whose postcode could not be placed in an authority are counted in no '
    'area. Regions are the English regions of the ONS lookup; Wales is one area. England and Wales only. Not an '
    'index: the mix of homes sold changes from period to period.'
)
METHODS = (METHOD, METHOD_INCREMENTAL)

REPO = Path(__file__).resolve().parents[2]
INCOMING = Path('_incoming/sold-prices-area-history')
OUT = Path('data/sold-prices/area-history')
PAGE = Path('sold-prices/history/areas/index.html')
SITEMAP = Path('sitemap.xml')
LLMS = Path('llms.txt')
PAGE_URL = 'https://data.yappman.com/sold-prices/history/areas/'
HISTORY_URL = 'https://data.yappman.com/sold-prices/history/'
STATE_FILE, INDEX_FILE = 'AH_STATE.json', 'ah_index.json'
LATEST_INDEX = 'index.json'


@dataclass(frozen=True)
class AreaHistory:
    state: dict[str, Any]
    index: dict[str, Any]
    shipped: dict[str, bytes]           # served name -> bytes (the index, every .json and .csv except the quarterly .json)
    checked_only: dict[str, bytes]      # the quarterly JSON files: verified, never published

    @property
    def month(self) -> str:
        return self.state['month']

    @property
    def totals(self) -> dict[str, Any]:
        return self.index['totals']


def _quarter(text: str) -> tuple[int, int]:
    m = LAST_QUARTER_RE.fullmatch(text)
    return int(m['y']), int(m['q'])


def served_names(entry: dict[str, Any]) -> list[str]:
    """The files of one index entry that the site serves: the quarterly authority files as CSV only."""
    if entry['kind'] == 'authority-quarter':
        return [entry['key'] + '.csv']
    return [entry['key'] + '.json', entry['key'] + '.csv']


def expected_keys() -> list[str]:
    keys = []
    for region in sorted(REGION_CODES):
        keys += [f'ah_{region}_year'] + [f'ah_{region}_qtr_{b}' for b, _, _ in BLOCKS]
    return keys + [REGIONS_BASE]


def check_area_history(raws: dict[str, bytes], live: dict[str, Any] | None, first_publish: bool) -> AreaHistory:
    """Every check, in order. `raws` holds AH_STATE.json, ah_index.json and each file found in the folder. Raises CheckFailed
    (number and reason) at the first failure."""
    for name, raw in raws.items():
        if len(raw) > MAX_FILE_BYTES:
            raise CheckFailed(1, f'{name} is larger than {MAX_FILE_BYTES} bytes')
    if STATE_FILE not in raws or INDEX_FILE not in raws:
        raise CheckFailed(1, 'AH_STATE.json or ah_index.json is missing', refused=True)
    state = _load_json(raws[STATE_FILE], 1, 'AH_STATE')
    index = _load_json(raws[INDEX_FILE], 1, 'ah_index.json')
    if not isinstance(state, dict) or not STATE_KEYS <= set(state):
        raise CheckFailed(1, 'AH_STATE lacks one of its eleven keys')
    if not isinstance(index, dict) or not INDEX_KEYS <= set(index):
        raise CheckFailed(1, 'ah_index.json lacks one of its keys')

    # 1. versions and columns
    for name, document in (('AH_STATE', state), ('the index', index)):
        if type(document['v']) is not int or document['v'] != AREA_VERSION:
            raise CheckFailed(1, f'{name} v must be {AREA_VERSION}')
    if index['columns'] != list(COLUMNS):
        raise CheckFailed(1, 'the index columns are not the eleven names in order')

    # 2. one build: the same month, lastYear, lastQuarter, postcodeRelease and builtAt in AH_STATE, the index and every file
    month, built_at, last_year, last_quarter, release = (state[k] for k in ('month', 'builtAt', 'lastYear', 'lastQuarter', 'postcodeRelease'))
    if not _is_month(month) or not (isinstance(built_at, str) and BUILT_AT_RE.fullmatch(built_at)):
        raise CheckFailed(2, 'AH_STATE month or builtAt is malformed')
    if not (isinstance(release, str) and RELEASE_RE.fullmatch(release)):
        raise CheckFailed(2, 'AH_STATE postcodeRelease is malformed')
    if type(last_year) is not int or not (FIRST_YEAR <= last_year < int(month[:4])):
        raise CheckFailed(2, 'AH_STATE lastYear is not a complete year before the month')
    if not (isinstance(last_quarter, str) and LAST_QUARTER_RE.fullmatch(last_quarter)) or not (last_year <= _quarter(last_quarter)[0] <= last_year + 1):
        raise CheckFailed(2, 'AH_STATE lastQuarter is malformed or not in the year after lastYear (or in lastYear)')
    if not (isinstance(state['regionLookupSha256'], str) and LOOKUP_SHA_RE.fullmatch(state['regionLookupSha256'])):
        raise CheckFailed(2, 'AH_STATE regionLookupSha256 is not a 64-character hex string')
    if not all(_is_count(state[k]) for k in ('authorities', 'regions', 'files', 'rows')):
        raise CheckFailed(2, 'AH_STATE authorities, regions, files or rows is not a whole number')
    same_keys = ('month', 'builtAt', 'postcodeRelease', 'lastYear', 'lastQuarter')
    if any(index[k] != state[k] for k in same_keys):
        raise CheckFailed(2, 'the index month, builtAt, postcodeRelease, lastYear or lastQuarter differs from AH_STATE')
    if type(index['firstYear']) is not int or index['firstYear'] != FIRST_YEAR:
        raise CheckFailed(2, f'the index firstYear is not {FIRST_YEAR}')
    if index['title'] != TITLE or index['licence'] != LICENCE or index['method'] not in METHODS:
        raise CheckFailed(2, 'the index title, licence or method is not the expected one')
    expected_attribution = _expected_attribution(built_at[:4])
    if index['attribution'] != expected_attribution:
        raise CheckFailed(8, 'the three attribution statements are missing or not word for word')

    # 3. the file list and the counts
    entries = index['files']
    totals = index['totals']
    if not isinstance(entries, list) or not 0 < len(entries) <= MAX_FILES or any(not isinstance(e, dict) or not ENTRY_KEYS <= set(e) for e in entries):
        raise CheckFailed(3, 'the index files are not a list of {key, region, regionName, kind, block, rows, authorities}')
    if not isinstance(totals, dict) or not TOTALS_KEYS <= set(totals) or not all(_is_count(totals[k]) for k in TOTALS_KEYS):
        raise CheckFailed(3, 'the index totals are not exactly their six whole numbers')
    keys = [e['key'] for e in entries]
    if sorted(keys) != sorted(expected_keys()):
        raise CheckFailed(3, 'the index files are not the three files of each of the ten regions and ah_regions')
    names_of: dict[str, str] = {}
    for e in entries:
        key = e['key']
        region_in_key = KEY_RE.fullmatch(key)['r']
        if key == REGIONS_BASE:
            ok = e['kind'] == 'region' and e['region'] is None and e['regionName'] is None and e['block'] is None
        else:
            kind = 'authority-year' if key.endswith('_year') else 'authority-quarter'
            block = None if kind == 'authority-year' else key.split('_qtr_')[1]
            ok = (e['kind'] == kind and e['region'] == region_in_key and e['block'] == block
                  and isinstance(e['regionName'], str) and NAME_RE.fullmatch(e['regionName']) is not None)
            if ok:
                names_of.setdefault(region_in_key, e['regionName'])
                ok = names_of[region_in_key] == e['regionName']
        if not ok or not _is_count(e['rows']) or not _is_count(e['authorities']):
            raise CheckFailed(3, f'the index entry of {key} has the wrong kind, block, region or counts')
    if names_of.get(WALES_CODE) != 'Wales':
        raise CheckFailed(3, 'Wales is not shown as W92000004, "Wales"')
    if sum(e['rows'] for e in entries) != totals['rows'] or totals['rows'] != state['rows']:
        raise CheckFailed(3, 'the index entries, totals.rows and AH_STATE.rows do not agree')
    if len(entries) != totals['files'] or totals['files'] != state['files']:
        raise CheckFailed(3, 'the file count differs from totals.files or AH_STATE.files')
    if totals['regions'] != state['regions'] or totals['regions'] != len(REGION_CODES) or totals['authorities'] != state['authorities']:
        raise CheckFailed(3, 'the regions or authorities total differs from AH_STATE (or the regions are not the ten expected)')

    shipped: dict[str, bytes] = {INDEX_FILE: raws[INDEX_FILE]}
    checked_only: dict[str, bytes] = {}
    authority_sales: dict[tuple[str, str, str, str], int] = defaultdict(int)   # (region, periodType, period, split) -> sales
    region_sales: dict[tuple[str, str, str, str], int] = {}
    authorities_seen: set[str] = set()
    total_authority_rows = 0
    for entry in entries:
        key = entry['key']
        json_name, csv_name = f'{key}.json', f'{key}.csv'
        if json_name not in raws or csv_name not in raws:
            raise CheckFailed(1, f'the files of {key} are missing', refused=True)
        document = _load_json(raws[json_name], 1, json_name)
        if not isinstance(document, dict) or not FILE_KEYS <= set(document):
            raise CheckFailed(1, f'{json_name} lacks one of its keys')
        if type(document['v']) is not int or document['v'] != AREA_VERSION:
            raise CheckFailed(1, f'{json_name} v must be {AREA_VERSION}')
        shared = {k: document[k] for k in ('month', 'lastYear', 'lastQuarter', 'postcodeRelease', 'builtAt', 'firstYear', 'title', 'licence', 'method')}
        if (shared != {'month': month, 'lastYear': last_year, 'lastQuarter': last_quarter, 'postcodeRelease': release, 'builtAt': built_at,
                       'firstYear': FIRST_YEAR, 'title': TITLE, 'licence': LICENCE, 'method': index['method']}
                or document['area'] != entry['region'] or document['kind'] != entry['kind'] or document['block'] != entry['block']):
            raise CheckFailed(2, f'{json_name}: month, lastYear, lastQuarter, postcodeRelease, builtAt, area, kind, block or text differs from the index '
                                 f'(a run failed midway: wait for the next run)')
        if document['attribution'] != index['attribution']:
            raise CheckFailed(8, f'{json_name}: the attribution differs from the index')
        if document['columns'] != list(COLUMNS):
            raise CheckFailed(1, f'{json_name}: the columns are not the eleven names in order')
        rows = document['rows']
        if not isinstance(rows, list) or len(rows) != entry['rows']:
            raise CheckFailed(3, f'{json_name}: the row count differs from the index')
        # 4. the CSV is the same build, cell for cell
        try:
            parsed = list(csv.reader(io.StringIO(raws[csv_name].decode('utf-8'), newline='')))
        except (UnicodeDecodeError, csv.Error):
            raise CheckFailed(4, f'{csv_name} is not UTF-8 CSV') from None
        if not parsed or parsed[0] != list(COLUMNS):
            raise CheckFailed(4, f'{csv_name}: the header is not the columns')
        if len(parsed) - 1 != len(rows):
            raise CheckFailed(4, f'{csv_name}: the row count differs from the JSON')
        codes: set[str] = set()
        for number, (cells, row) in enumerate(zip(parsed[1:], rows), start=1):
            where = f'{json_name} row {number}'
            if not isinstance(row, dict) or set(row) != set(COLUMNS):
                raise CheckFailed(5, f'{where} does not have exactly the eleven fields')
            if len(cells) != len(COLUMNS) or not all(cell_matches(cell, row[c]) for cell, c in zip(cells, COLUMNS)):
                raise CheckFailed(4, f'{csv_name} row {number} differs from the JSON row')
            # 5. every cell has the expected kind, and what the page says is enforced
            ptype, period, geography, code = row['periodType'], row['period'], row['geography'], row['code']
            if ptype not in ('year', 'quarter') or geography not in ('authority', 'region'):
                raise CheckFailed(5, f'{where}: periodType or geography is not one of its two values')
            if not isinstance(period, str):
                raise CheckFailed(5, f'{where}: the period is not text')
            if ptype == 'year':
                if not re.fullmatch(r'[0-9]{4}', period) or not (FIRST_YEAR <= int(period) <= last_year):
                    raise CheckFailed(5, f'{where}: the year is outside {FIRST_YEAR} to {last_year}')
                year = int(period)
            else:
                if not PERIOD_QUARTER_RE.fullmatch(period) or not ((FIRST_YEAR, 1) <= _quarter(period) <= _quarter(last_quarter)):
                    raise CheckFailed(5, f'{where}: the quarter is outside {FIRST_YEAR}-Q1 to {last_quarter}')
                year = _quarter(period)[0]
            if row['split'] not in (YEAR_SPLITS if ptype == 'year' else QUARTER_SPLITS):
                raise CheckFailed(5, f'{where}: the split is not one allowed for a {ptype} row')
            kind = entry['kind']
            if (kind == 'authority-year' and (geography, ptype) != ('authority', 'year')) or \
               (kind == 'authority-quarter' and (geography, ptype) != ('authority', 'quarter')) or (kind == 'region' and geography != 'region'):
                raise CheckFailed(5, f'{where}: the geography or period type does not belong in this file')
            if kind == 'authority-quarter':
                low, high = next((lo, hi) for b, lo, hi in BLOCKS if b == entry['block'])
                if year < low or (high is not None and year > high):
                    raise CheckFailed(5, f'{where}: the quarter is outside the block {entry["block"]}')
            if geography == 'authority':
                if not (isinstance(code, str) and AUTHORITY_CODE_RE.fullmatch(code)) or (code.startswith('W') != (entry['region'] == WALES_CODE)):
                    raise CheckFailed(5, f'{where}: the authority code is not E06, E07, E08, E09 or W06 (and Welsh only in Wales)')
            elif code not in REGION_CODES:
                raise CheckFailed(5, f'{where}: the region code is not E12000001 to E12000009 or W92000004')
            if not (isinstance(row['name'], str) and NAME_RE.fullmatch(row['name'])):
                raise CheckFailed(5, f'{where}: the name is not a plain name')
            if geography == 'region' and row['name'] != names_of[code]:
                raise CheckFailed(5, f'{where}: the region name differs from the index')
            if not _is_count(row['sales']) or row['sales'] < 1:
                raise CheckFailed(5, f'{where}: sales is not a whole number of at least 1')
            if not all(_is_number_or_empty(row[c]) for c in FIGURE_COLUMNS):
                raise CheckFailed(5, f'{where}: a figure is not a number or empty')
            if any((row[c] is None) != (row['sales'] < MIN_SALES) for c in FIGURE_COLUMNS):
                raise CheckFailed(5, f'{where}: a figure is blank or shown against its sales')
            if type(row['lowSample']) is not bool or row['lowSample'] != (row['sales'] < LOW_SAMPLE_BELOW):
                raise CheckFailed(5, f'{where}: lowSample does not match sales')
            codes.add(code)
            group = (entry['region'] if geography == 'authority' else code, ptype, period, row['split'])
            if geography == 'authority':
                authority_sales[group] += row['sales']
                authorities_seen.add(code)
                total_authority_rows += 1
            else:
                if group in region_sales:
                    raise CheckFailed(5, f'{where}: a region row repeats')
                region_sales[group] = row['sales']
        if entry['kind'] != 'region' and len(codes) > entry['authorities']:
            raise CheckFailed(3, f'{json_name}: more authorities than the index says')
        for name in served_names(entry):
            shipped[name] = raws[name]
        if entry['kind'] == 'authority-quarter':
            checked_only[json_name] = raws[json_name]
    # 6. the authorities and the region sums
    if len(authorities_seen) != totals['authorities']:
        raise CheckFailed(3, 'the authorities found in the files differ from totals.authorities')
    if dict(authority_sales) != region_sales:
        raise CheckFailed(6, "a region row's sales differ from the sum of its authorities' sales for the same period and split (or a row is missing)")
    if not _is_count(totals['suppressed']) or not _is_count(totals['unassignedSales']):
        raise CheckFailed(3, 'totals.suppressed or totals.unassignedSales is not a whole number')

    # 7. not older than what is live; a first publish only when nothing is live
    if live is None:
        if not first_publish:
            raise CheckFailed(7, 'nothing is live: run with --first-publish for the first area history', refused=True)
    else:
        if first_publish:
            raise CheckFailed(7, '--first-publish refused: an area history is already live', refused=True)
        if month < live['month'] or (month == live['month'] and _instant(built_at) < _instant(live['builtAt'])):
            raise CheckFailed(7, f'the area history ({month}, built {built_at}) is older than the live one')
    return AreaHistory(state, index, shipped, checked_only)


def _expected_attribution(year: str) -> list[str]:
    return [
        f'Contains HM Land Registry data © Crown copyright and database right {year}. This data is licensed under the Open Government Licence v3.0.',
        'Local authority codes: Source: Office for National Statistics licensed under the Open Government Licence v3.0. Contains OS data © '
        f'Crown copyright and database right {year}. Contains Royal Mail data © Royal Mail copyright and database right {year}.',
        REGION_ATTRIBUTION,
    ]


assert all(p.fullmatch(s) for p, s in zip(ATTRIBUTION_RES, _expected_attribution('2026')))   # the monthly build's patterns agree with ours


def live_area_history(root: Path) -> dict[str, Any] | None:
    """The month and builtAt of the live latest index, or None before the first publish."""
    path = root / OUT / LATEST_INDEX
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_bytes().decode('utf-8'))
        live = {'month': document['month'], 'builtAt': document['builtAt']}
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        raise CheckFailed(7, 'the live latest index cannot be read') from None
    if not (_is_month(live['month']) and isinstance(live['builtAt'], str) and BUILT_AT_RE.fullmatch(live['builtAt'])):
        raise CheckFailed(7, 'the live latest index has a malformed month or builtAt (edited by hand?)')
    return live


def _region(text: str, name: str, content: str) -> str:
    start, end = f'<!-- area-history:{name} -->', f'<!-- /area-history:{name} -->'
    if text.count(start) != 1 or text.count(end) != 1 or text.index(start) > text.index(end):
        raise TemplateBroken(f'the page has no single {name} region')
    head, rest = text.split(start)
    _, tail = rest.split(end)
    return f'{head}{start}\n{content}{end}{tail}'


def archived_months(root: Path) -> list[dict[str, Any]]:
    """Each dated folder under data/sold-prices/area-history/ with its index, newest first."""
    found = []
    base = root / OUT
    for folder in sorted(base.iterdir(), reverse=True) if base.exists() else ():
        if folder.is_dir() and re.fullmatch(r'[0-9]{4}-(?:0[1-9]|1[0-2])', folder.name) and (folder / INDEX_FILE).exists():
            doc = json.loads((folder / INDEX_FILE).read_bytes().decode('utf-8'))
            size = sum(p.stat().st_size for p in folder.iterdir() if p.is_file())
            found.append({'month': folder.name, 'builtAt': doc['builtAt'], 'lastYear': doc['lastYear'], 'lastQuarter': doc['lastQuarter'],
                          'files': doc['totals']['files'], 'rows': doc['totals']['rows'], 'bytes': size})
    return found


def retention(months: list[dict[str, Any]]) -> dict[str, Any]:
    """The rule approved by Russell: the latest vintage plus ONE year-end vintage (last quarter = the fourth quarter of its last
    year), no more. `months` is newest first. Returns what to keep and what a person should delete; nothing is deleted here."""
    keep = [months[0]['month']] if months else []
    for m in months:
        if m['lastQuarter'] == f'{m["lastYear"]}-Q4':
            keep.append(m['month']) if m['month'] not in keep else None
            break
    remove = [m['month'] for m in months if m['month'] not in keep]
    return {'keep': keep, 'remove': remove, 'removeBytes': sum(m['bytes'] for m in months if m['month'] in remove)}


def render_regions(history: AreaHistory, months: list[dict[str, Any]]) -> dict[str, str]:
    """The regions, from checked fields only, every value escaped. `months` lists the dated folders after this publish."""
    e, d, t = html.escape, history.index, history.totals
    summary = (f'<p>Latest build: {e(d["month"])}. Years {d["firstYear"]} to {d["lastYear"]}, quarters {d["firstYear"]}-Q1 to {e(d["lastQuarter"])}; '
               f'{t["rows"]:,} rows for {t["authorities"]:,} local authorities in {t["regions"]} regions (Wales counts as one). Built {e(d["builtAt"][:10])}, '
               f'postcode release {e(d["postcodeRelease"])}.</p>\n')
    folder = f'/data/sold-prices/area-history/{d["month"]}'

    def link(name: str) -> str:
        return f'<a href="{folder}/{e(name)}">{e(name)}</a> ({_size(len(history.shipped[name]))})'

    by_key = {entry['key']: entry for entry in d['files']}
    lines = ['<div class="table-wrap"><table><thead><tr><th>Region</th><th class="num">Authorities</th><th>Years</th><th>Quarters 1995 to 2009</th>'
             '<th>Quarters 2010 onwards</th></tr></thead>', '<tbody>']
    regions = sorted((by_key[k] for k in by_key if k.endswith('_year')), key=lambda x: x['regionName'])
    for entry in regions:
        base = entry['key'][:-len('_year')]
        lines.append(f'<tr><td>{e(entry["regionName"])}</td><td class="num">{entry["authorities"]:,}</td>'
                     f'<td>{link(base + "_year.csv")}<br>{link(base + "_year.json")}</td>'
                     f'<td>{link(base + "_qtr_1995-2009.csv")}</td><td>{link(base + "_qtr_2010-onwards.csv")}</td></tr>')
    reg = by_key[REGIONS_BASE]
    lines.append(f'<tr><td>All regions (region rows, years and quarters)</td><td class="num">{reg["authorities"]:,}</td>'
                 f'<td colspan="3">{link(REGIONS_BASE + ".csv")}<br>{link(REGIONS_BASE + ".json")}</td></tr>')
    lines.append('</tbody></table></div>')
    downloads = '\n'.join(lines) + '\n'
    rows = ['<div class="table-wrap"><table><thead><tr><th>Build month</th><th>Built</th><th>Years to</th><th>Quarters to</th><th class="num">Rows</th>'
            '<th>Index</th></tr></thead>', '<tbody>']
    for m in months:
        rows.append(f'<tr><td>{e(m["month"])}</td><td>{e(m["builtAt"][:10])}</td><td>{m["lastYear"]}</td><td>{e(m["lastQuarter"])}</td>'
                    f'<td class="num">{m["rows"]:,}</td><td><a href="/data/sold-prices/area-history/{e(m["month"])}/{INDEX_FILE}">{INDEX_FILE}</a></td></tr>')
    rows.append('</tbody></table></div>')
    archive = '\n'.join(rows) + '\n'
    attribution = ''.join(f'<p class="attribution">{e(a)}</p>\n' for a in d['attribution'])
    method = f'<p class="method">{e(d["method"])}</p>\n'
    unassigned = (f'  <li>Authorities are today&rsquo;s authorities applied back to 1995: a sale counts in the authority its postcode is in today, not the one '
                  f'it was in at the time. Sales whose postcode could not be placed in an authority are in no area: {t["unassignedSales"]:,} sales '
                  f'in this build. They are left out of every authority and region figure.</li>\n')
    return {'summary': summary, 'downloads': downloads, 'archive': archive, 'attribution': attribution, 'method': method, 'unassigned': unassigned}


@dataclass(frozen=True)
class Plan:
    files: list[tuple[Path, bytes]]
    page: str
    sitemap: str
    llms: str
    done: list[str]
    retention: dict[str, Any]


LLMS_LINE = ('- [Median sold prices by local authority and region, by year and quarter]({url}): A free table of median sold prices and quartiles for each '
             'local authority and region of England and Wales, by calendar year and quarter from 1995, from HM Land Registry Price Paid Data: standard '
             'sales only, one split at a time, as CSV and JSON under the Open Government Licence v3.0.')


def plan_publish(root: Path, history: AreaHistory, today: str) -> Plan:
    """Everything the publish writes, worked out in memory. Raises CheckFailed or TemplateBroken before anything is written."""
    base = root / OUT
    folder = base / history.month
    files: list[tuple[Path, bytes]] = []
    done: list[str] = []
    if folder.exists():
        same = (all((folder / name).exists() and (folder / name).read_bytes() == data for name, data in history.shipped.items())
                and {p.name for p in folder.iterdir()} == set(history.shipped))
        if not same:
            raise CheckFailed(7, f'the archive folder for {history.month} exists and differs: an archive is never rewritten (a person decides)')
        done.append(f'the {history.month} archive is already as fetched')
    else:
        for name, data in history.shipped.items():
            files.append((folder / name, data))
        done.append(f'archived {len(history.shipped)} files under {history.month}/')
    files.append((base / LATEST_INDEX, history.shipped[INDEX_FILE]))
    done.append(f'wrote {LATEST_INDEX}')
    months = archived_months(root)
    if not any(m['month'] == history.month for m in months):
        months.append({'month': history.month, 'builtAt': history.index['builtAt'], 'lastYear': history.index['lastYear'],
                       'lastQuarter': history.index['lastQuarter'], 'files': history.totals['files'], 'rows': history.totals['rows'],
                       'bytes': sum(len(b) for b in history.shipped.values())})
        months.sort(key=lambda m: m['month'], reverse=True)
    try:
        page = (root / PAGE).read_text(encoding='utf-8')
        sitemap = (root / SITEMAP).read_text(encoding='utf-8')
        llms = (root / LLMS).read_text(encoding='utf-8')
    except OSError:
        raise TemplateBroken('the page, the sitemap or llms.txt is missing') from None
    for name, content in render_regions(history, months).items():
        page = _region(page, name, content)
    for statement in history.index['attribution']:      # the attribution is shown on the page
        if f'<p class="attribution">{html.escape(statement)}</p>' not in page:
            raise CheckFailed(8, 'the attribution is not on the page')
    if f'<p class="method">{html.escape(history.index["method"])}</p>' not in page:
        raise CheckFailed(8, 'the method is not on the page')
    newline = '\r\n' if '\r\n' in sitemap else '\n'
    text = sitemap.replace('\r\n', '\n')
    pattern = re.compile(r'(<loc>' + re.escape(PAGE_URL) + r'</loc>\s*<lastmod>)[0-9-]{10}(</lastmod>)')
    if len(pattern.findall(text)) == 1:
        text = pattern.sub(rf'\g<1>{today}\g<2>', text)
    elif not pattern.findall(text) and PAGE_URL not in text:
        anchor = f'    <loc>{HISTORY_URL}</loc>'
        if text.count(anchor) != 1:
            raise TemplateBroken('sitemap.xml has no single entry for /sold-prices/history/ to put the new page after')
        j = text.index('  </url>\n', text.index(anchor)) + len('  </url>\n')
        text = text[:j] + f'  <url>\n    <loc>{PAGE_URL}</loc>\n    <lastmod>{today}</lastmod>\n  </url>\n' + text[j:]
    else:
        raise TemplateBroken('sitemap.xml has more than one or a malformed entry for the page')
    sitemap_out = text.replace('\n', newline)
    llms_newline = '\r\n' if '\r\n' in llms else '\n'
    llines = llms.replace('\r\n', '\n').split('\n')
    present = [i for i, line in enumerate(llines) if f'({PAGE_URL})' in line]
    if not present:
        at = [i for i, line in enumerate(llines) if f'({HISTORY_URL})' in line]
        if len(at) != 1:
            raise TemplateBroken('llms.txt has no single line for /sold-prices/history/ to put the new page after')
        llines.insert(at[0] + 1, LLMS_LINE.format(url=PAGE_URL))
    elif len(present) > 1:
        raise TemplateBroken('llms.txt has more than one line for the page')
    done.append('updated sold-prices/history/areas/index.html, its sitemap entry and its llms.txt line')
    return Plan(files, page, sitemap_out, llms_newline.join(llines), done, retention(months))


def write_plan(root: Path, plan: Plan) -> None:
    for path, data in plan.files:
        path.parent.mkdir(parents=True, exist_ok=True)
        _replace(path, data)
    _replace(root / PAGE, plan.page.encode('utf-8'))
    _replace(root / SITEMAP, plan.sitemap.encode('utf-8'))
    _replace(root / LLMS, plan.llms.encode('utf-8'))


def load_incoming(folder: Path) -> dict[str, bytes]:
    """AH_STATE.json, ah_index.json and the ah_* files the folder holds (the index decides which are used)."""
    raws: dict[str, bytes] = {}
    for path in sorted(folder.iterdir()):
        if path.is_file() and (path.name in (STATE_FILE, INDEX_FILE) or re.fullmatch(r'ah_[A-Za-z0-9_.\-]{1,80}\.(?:json|csv)', path.name)):
            raws[path.name] = path.read_bytes()
    return raws


def main(argv: list[str] | None = None, *, root: Path = REPO, today: str | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='the checks only; writes nothing')
    mode.add_argument('--publish', action='store_true')
    parser.add_argument('--first-publish', action='store_true', help='only when no area history is live yet')
    parser.add_argument('--from', dest='source', default=None, help=f'the folder of fetched files (default {INCOMING}), inside this repo')
    args = parser.parse_args(argv)
    if not is_this_repo(root):
        print(json.dumps({'status': 'refused', 'code': 'not-the-data-yappman-repo'}))
        return 2
    folder = root / (args.source or INCOMING)
    try:
        folder.resolve().relative_to(root.resolve())
        raws = load_incoming(folder)
    except (OSError, ValueError):
        print(json.dumps({'status': 'refused', 'code': 'incoming-files-missing', 'folder': str(args.source or INCOMING)}))
        return 2
    live = None
    try:
        live = live_area_history(root)
        history = check_area_history(raws, live, args.first_publish)
        if live is not None and live['month'] == history.month and live['builtAt'] == history.state['builtAt']:
            print(json.dumps({'status': 'nothing-new', 'month': history.month, 'builtAt': history.state['builtAt']}))
            return 0
        plan = plan_publish(root, history, today or datetime.now(UTC).date().isoformat())
    except CheckFailed as failure:
        print(json.dumps({'status': 'refused' if failure.refused else 'held', 'check': failure.check, 'reason': str(failure), 'live': live}))
        return 2 if failure.refused else 3
    except TemplateBroken as broken:
        print(json.dumps({'status': 'held', 'code': 'template-broken', 'reason': str(broken)}))
        return 3
    sizes = [len(data) for data in history.shipped.values()]      # what the site tree will hold for this build (one copy)
    summary = {'month': history.month, 'builtAt': history.state['builtAt'], 'rows': history.totals['rows'], 'authorities': history.totals['authorities'],
               'regions': history.totals['regions'], 'filesFetched': len(history.shipped) + len(history.checked_only), 'filesShipped': len(sizes),
               'shippedBytes': sum(sizes), 'largestShippedBytes': max(sizes), 'notShippedBytes': sum(len(b) for b in history.checked_only.values()),
               'unassignedSales': history.totals['unassignedSales'], 'live': live}
    if args.check:
        print(json.dumps({'status': 'checks-passed', **summary, 'wouldDo': plan.done, 'retention': plan.retention}))
        return 0
    write_plan(root, plan)
    print(json.dumps({'status': 'published', **summary, 'done': plan.done, 'retention': plan.retention}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
