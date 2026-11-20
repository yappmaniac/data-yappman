"""Median sold prices by postcode district and year (history): the website build (no network, no token).

Turns the files saved in _incoming/sold-prices-history/ (HS_STATE.json, history_index.json and, for each area the index
lists, history_<AREA>.json and history_<AREA>.csv) into the download files and the page /sold-prices/history/. Run from
anywhere (paths are anchored to this repo):

    python -I -B docs/release/history_table_site.py --check                    # the checks only, writes nothing
    python -I -B docs/release/history_table_site.py --publish [--first-publish]

Source and checks: Orchestrator drafts/sessions/property/history-table-gates-19-nov.md, gate 3, and the Actor's own
format (price_paid/src/district_history.py, HISTORY_VERSION 1). The separate monthly table (/sold-prices/, its files and
docs/release/district_table_site.py) is NOT touched; this module only imports that file's helpers.

What it does:
- Reads the saved files and publishes only when every check passes; otherwise it writes nothing and what is live stays
  live (exit 3). Only the areas the index lists are used (an older area file left in the folder is ignored).
  Checks: versions all 1; month, lastYear, postcodeRelease and builtAt equal in HS_STATE, the index and EVERY area file;
  per-area row counts equal the index's, their total equals HS_STATE.rows, and the area count equals HS_STATE.areas;
  the CSV header equals the columns and the CSV rows equal the JSON rows; split is one of the nine; year is between
  firstYear and lastYear; sales is at least 1; the median and the quartiles are numbers or empty, empty exactly when
  sales is under 5; lowSample is true exactly when sales is under 20; the two attribution statements, the licence and
  the method are present and exactly as expected (so what is checked is exactly what is shown); no JSON object repeats
  a key; every key set and type is exact; no row holds anything but its nine fields.
- Plans everything in memory first (the page and the sitemap included) and writes only when the plan is complete: the
  data files, then the page, then the sitemap.
- Writes data/sold-prices/history/<month>/ (history_<AREA>.json and .csv for every area, and history_index.json: the
  dated archive of that build, written once and never rewritten) and data/sold-prices/history/index.json (the latest
  build's index: the page reads it to find the newest folder). A month whose folder exists and differs is held (exit 3):
  an archive is never rewritten, so a person decides.
- Rewrites only the marked parts of sold-prices/history/index.html (summary, downloads, archive, attribution and method,
  taken from the checked JSON and escaped) and that page's lastmod in sitemap.xml. The files are published as fetched
  (byte for byte).

Exit codes: 0 published, or nothing new; 2 refused (usage, wrong folder, files missing, or --first-publish against a
live history); 3 a check failed or the page template is broken, nothing written.
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
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from district_table_site import (  # noqa: E402  (the reviewed helpers of the monthly table's build, unchanged)
    BUILT_AT_RE, DISTRICT_RE, LICENCE, LOW_SAMPLE_BELOW, MAX_FILE_BYTES, MIN_SALES, AUTHORITIES_RE, RELEASE_RE,
    CheckFailed, TemplateBroken, _attribution_ok, _instant, _is_count, _is_month, _is_number_or_empty, _load_json,
    _replace, _size, cell_matches, is_this_repo,
)

HISTORY_VERSION = 1
TITLE = 'Median sold prices by postcode district and year, England and Wales'
FIRST_YEAR = 1995
COLUMNS = ('year', 'district', 'localAuthorityCodes', 'split', 'sales', 'median', 'lowerQuartile', 'upperQuartile', 'lowSample')
SPLITS = ('all', 'detached', 'semi-detached', 'terraced', 'flat', 'freehold', 'leasehold', 'new-build', 'existing')
STATE_KEYS = frozenset({'v', 'month', 'lastYear', 'postcodeRelease', 'builtAt', 'districts', 'rows', 'areas'})
INDEX_KEYS = frozenset({'v', 'title', 'firstYear', 'lastYear', 'month', 'postcodeRelease', 'builtAt', 'licence', 'attribution',
                        'method', 'columns', 'areas'})
AREA_KEYS = frozenset({'v', 'title', 'area', 'firstYear', 'lastYear', 'month', 'postcodeRelease', 'builtAt', 'licence',
                       'attribution', 'method', 'columns', 'rows'})
AREA_ENTRY_KEYS = frozenset({'area', 'districts', 'rows'})
FIGURE_COLUMNS = ('median', 'lowerQuartile', 'upperQuartile')
MAX_AREAS = 200
# The Actor's method sentence, word for word (price_paid/src/district_history.py METHOD, MIN_SALES 5). Pinned so no other
# free text reaches the public files; if the Actor's wording changes, the build is held until this matches.
METHOD = (
    'Category A (standard price paid) sales only, by transfer date, one row per postcode district, calendar year '
    'and split (a split is one grouping at a time: all sales, one property type, one tenure, or new-build or '
    'existing; they are not crossed). Medians and quartiles (inclusive method) in whole pounds, nominal and not '
    'adjusted for inflation; null when a year has fewer than 5 sales (a quality threshold: every sale '
    'is already published by HM Land Registry). Rows with no sales are left out. Only complete calendar years are '
    'shown, and the latest year is as at the month the file was built; sales registered later are added when the '
    'file is next rebuilt (when a new year is complete or the postcode release changes). Districts are those current in the ONS '
    'Postcode Directory release named in the file. Not an index: the mix of homes sold changes from year to year.'
)
AREA_RE = re.compile(r'[A-Z]{1,2}')

REPO = Path(__file__).resolve().parents[2]
INCOMING = Path('_incoming/sold-prices-history')
OUT = Path('data/sold-prices/history')
PAGE = Path('sold-prices/history/index.html')
SITEMAP = Path('sitemap.xml')
PAGE_URL = 'https://data.yappman.com/sold-prices/history/'
STATE_FILE, INDEX_FILE = 'HS_STATE.json', 'history_index.json'
LATEST_INDEX = 'index.json'


@dataclass(frozen=True)
class History:
    state: dict[str, Any]
    index: dict[str, Any]
    files: dict[str, bytes]             # served name -> bytes: history_index.json and every area's .json and .csv
    area_files: list[str]               # the areas, in the index's order

    @property
    def month(self) -> str:
        return self.state['month']

    @property
    def rows(self) -> int:
        return self.state['rows']


def check_history(raws: dict[str, bytes], live: dict[str, Any] | None, first_publish: bool) -> History:
    """Every check of gate 3, in order. `raws` holds HS_STATE.json, history_index.json and each area file found in the folder.
    Raises CheckFailed (number and reason) at the first failure."""
    for name, raw in raws.items():
        if len(raw) > MAX_FILE_BYTES:
            raise CheckFailed(1, f'{name} is larger than {MAX_FILE_BYTES} bytes')
    if STATE_FILE not in raws or INDEX_FILE not in raws:
        raise CheckFailed(1, 'HS_STATE.json or history_index.json is missing', refused=True)
    state = _load_json(raws[STATE_FILE], 1, 'HS_STATE')
    index = _load_json(raws[INDEX_FILE], 1, 'history_index.json')
    if not isinstance(state, dict) or set(state) != STATE_KEYS:
        raise CheckFailed(1, 'HS_STATE does not have exactly its eight keys')
    if not isinstance(index, dict) or set(index) != INDEX_KEYS:
        raise CheckFailed(1, 'history_index.json does not have exactly its keys')

    # 1. versions and columns
    for name, document in (('HS_STATE', state), ('the index', index)):
        if type(document['v']) is not int or document['v'] != HISTORY_VERSION:
            raise CheckFailed(1, f'{name} v must be {HISTORY_VERSION}')
    if index['columns'] != list(COLUMNS):
        raise CheckFailed(1, 'the index columns are not the nine names in order')

    # 2. one build: the same month, lastYear, postcodeRelease and builtAt in HS_STATE, the index (and below, every area file)
    month, built_at, last_year, release = state['month'], state['builtAt'], state['lastYear'], state['postcodeRelease']
    if not _is_month(month) or not (isinstance(built_at, str) and BUILT_AT_RE.fullmatch(built_at)):
        raise CheckFailed(2, 'HS_STATE month or builtAt is malformed')
    if not (isinstance(release, str) and RELEASE_RE.fullmatch(release)):
        raise CheckFailed(2, 'HS_STATE postcodeRelease is malformed')
    if type(last_year) is not int or not (FIRST_YEAR <= last_year < int(month[:4])):
        raise CheckFailed(2, 'HS_STATE lastYear is not a complete year before the month')
    if not all(_is_count(state[k]) for k in ('districts', 'rows', 'areas')):
        raise CheckFailed(2, 'HS_STATE districts, rows or areas is not a whole number')
    if (index['month'], index['builtAt'], index['postcodeRelease'], index['lastYear']) != (month, built_at, release, last_year):
        raise CheckFailed(2, 'the index month, builtAt, postcodeRelease or lastYear differs from HS_STATE')
    if index['firstYear'] != FIRST_YEAR or type(index['firstYear']) is not int:
        raise CheckFailed(2, f'the index firstYear is not {FIRST_YEAR}')
    if index['title'] != TITLE or index['licence'] != LICENCE or index['method'] != METHOD:
        raise CheckFailed(2, 'the index title, licence or method is not the expected one')
    # 8 (stated early because each area file repeats it): the attribution, word for word, with the build year
    if not _attribution_ok(index['attribution'], built_at[:4]):
        raise CheckFailed(8, 'the two attribution statements are missing or not word for word')

    entries = index['areas']
    if not isinstance(entries, list) or not 0 < len(entries) <= MAX_AREAS or any(not isinstance(e, dict) or set(e) != AREA_ENTRY_KEYS for e in entries):
        raise CheckFailed(3, 'the index areas are not a list of {area, districts, rows}')
    areas = [e['area'] for e in entries]
    if not all(isinstance(a, str) and AREA_RE.fullmatch(a) for a in areas) or len(set(areas)) != len(areas):
        raise CheckFailed(3, 'an index area is not one or two capital letters, or repeats')
    if not all(_is_count(e['districts']) and _is_count(e['rows']) for e in entries):
        raise CheckFailed(3, 'an index districts or rows count is not a whole number')
    # 3. counts agree
    if len(areas) != state['areas']:
        raise CheckFailed(3, 'the index area count differs from HS_STATE.areas')
    if sum(e['rows'] for e in entries) != state['rows']:
        raise CheckFailed(3, 'the index row total differs from HS_STATE.rows')
    if sum(e['districts'] for e in entries) != state['districts']:
        raise CheckFailed(3, 'the index district total differs from HS_STATE.districts')

    files: dict[str, bytes] = {INDEX_FILE: raws[INDEX_FILE]}
    for entry in entries:
        area = entry['area']
        json_name, csv_name = f'history_{area}.json', f'history_{area}.csv'
        if json_name not in raws or csv_name not in raws:
            raise CheckFailed(1, f'the files of area {area} are missing', refused=True)
        document = _load_json(raws[json_name], 1, json_name)
        if not isinstance(document, dict) or set(document) != AREA_KEYS:
            raise CheckFailed(1, f'{json_name} does not have exactly its keys')
        if type(document['v']) is not int or document['v'] != HISTORY_VERSION:
            raise CheckFailed(1, f'{json_name} v must be {HISTORY_VERSION}')
        same = {k: document[k] for k in ('month', 'lastYear', 'postcodeRelease', 'builtAt', 'firstYear', 'title', 'licence', 'method')}
        if same != {'month': month, 'lastYear': last_year, 'postcodeRelease': release, 'builtAt': built_at, 'firstYear': FIRST_YEAR,
                    'title': TITLE, 'licence': LICENCE, 'method': METHOD} or document['area'] != area:
            raise CheckFailed(2, f'{json_name}: month, lastYear, postcodeRelease, builtAt, area or text differs from the index (a run failed midway: wait for the next run)')
        if document['attribution'] != index['attribution']:
            raise CheckFailed(8, f'{json_name}: the attribution differs from the index')
        if document['columns'] != list(COLUMNS):
            raise CheckFailed(1, f'{json_name}: the columns are not the nine names in order')
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
        districts: set[str] = set()
        for number, (cells, row) in enumerate(zip(parsed[1:], rows), start=1):
            if not isinstance(row, dict) or set(row) != set(COLUMNS):
                raise CheckFailed(5, f'{json_name} row {number} does not have exactly the nine fields')
            if len(cells) != len(COLUMNS) or not all(cell_matches(cell, row[c]) for cell, c in zip(cells, COLUMNS)):
                raise CheckFailed(4, f'{csv_name} row {number} differs from the JSON row')
            # 5. every cell has the expected kind, and what the page says is enforced
            if row['split'] not in SPLITS:
                raise CheckFailed(5, f'{json_name} row {number}: the split is not one of the nine')
            if type(row['year']) is not int or not (FIRST_YEAR <= row['year'] <= last_year):
                raise CheckFailed(5, f'{json_name} row {number}: the year is outside {FIRST_YEAR} to {last_year}')
            if not (isinstance(row['district'], str) and DISTRICT_RE.fullmatch(row['district']) and row['district'].startswith(area)
                    and row['district'][len(area):][:1].isdigit()):
                raise CheckFailed(5, f'{json_name} row {number}: the district is not an outcode of the area')
            if not (isinstance(row['localAuthorityCodes'], str) and AUTHORITIES_RE.fullmatch(row['localAuthorityCodes'])):
                raise CheckFailed(5, f'{json_name} row {number}: the authority codes')
            if not _is_count(row['sales']) or row['sales'] < 1:
                raise CheckFailed(5, f'{json_name} row {number}: sales is not a whole number of at least 1')
            if not all(_is_number_or_empty(row[c]) for c in FIGURE_COLUMNS):
                raise CheckFailed(5, f'{json_name} row {number}: a figure is not a number or empty')
            if any((row[c] is None) != (row['sales'] < MIN_SALES) for c in FIGURE_COLUMNS):
                raise CheckFailed(5, f'{json_name} row {number}: a figure is blank or shown against its sales')
            if type(row['lowSample']) is not bool or row['lowSample'] != (row['sales'] < LOW_SAMPLE_BELOW):
                raise CheckFailed(5, f'{json_name} row {number}: lowSample does not match sales')
            districts.add(row['district'])
        if len(districts) > entry['districts']:
            raise CheckFailed(3, f'{json_name}: more districts than the index says')
        files[json_name], files[csv_name] = raws[json_name], raws[csv_name]

    # 6. not older than what is live; a first publish only when nothing is live
    if live is None:
        if not first_publish:
            raise CheckFailed(6, 'nothing is live: run with --first-publish for the first history', refused=True)
    else:
        if first_publish:
            raise CheckFailed(6, '--first-publish refused: a history is already live', refused=True)
        if month < live['month'] or (month == live['month'] and _instant(built_at) < _instant(live['builtAt'])):
            raise CheckFailed(6, f'the history ({month}, built {built_at}) is older than the live one')
    return History(state, index, files, areas)


def live_history(root: Path) -> dict[str, Any] | None:
    """The month and builtAt of the live latest index, or None before the first publish."""
    path = root / OUT / LATEST_INDEX
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_bytes().decode('utf-8'))
        live = {'month': document['month'], 'builtAt': document['builtAt']}
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        raise CheckFailed(6, 'the live latest index cannot be read') from None
    if not (_is_month(live['month']) and isinstance(live['builtAt'], str) and BUILT_AT_RE.fullmatch(live['builtAt'])):
        raise CheckFailed(6, 'the live latest index has a malformed month or builtAt (edited by hand?)')
    return live


def _region(text: str, name: str, content: str) -> str:
    start, end = f'<!-- history-table:{name} -->', f'<!-- /history-table:{name} -->'
    if text.count(start) != 1 or text.count(end) != 1 or text.index(start) > text.index(end):
        raise TemplateBroken(f'the page has no single {name} region')
    head, rest = text.split(start)
    _, tail = rest.split(end)
    return f'{head}{start}\n{content}{end}{tail}'


def archived_months(root: Path) -> list[dict[str, Any]]:
    """Each dated folder under data/sold-prices/history/ with its index, newest first: month, builtAt, lastYear, areas, rows."""
    found = []
    base = root / OUT
    for folder in sorted(base.iterdir(), reverse=True) if base.exists() else ():
        if folder.is_dir() and re.fullmatch(r'[0-9]{4}-(?:0[1-9]|1[0-2])', folder.name) and (folder / INDEX_FILE).exists():
            doc = json.loads((folder / INDEX_FILE).read_bytes().decode('utf-8'))
            found.append({'month': folder.name, 'builtAt': doc['builtAt'], 'lastYear': doc['lastYear'], 'areas': len(doc['areas']),
                          'rows': sum(a['rows'] for a in doc['areas'])})
    return found


def render_regions(history: History, months: list[dict[str, Any]]) -> dict[str, str]:
    """The regions, from checked fields only, every value escaped. `months` lists the dated folders after this publish."""
    e, d = html.escape, history.index
    summary = (f'<p>Latest build: {e(d["month"])}. Years {d["firstYear"]} to {d["lastYear"]}; {history.rows:,} rows for '
               f'{history.state["districts"]:,} districts in {len(history.area_files)} postcode areas. Built {e(d["builtAt"][:10])}, '
               f'postcode release {e(d["postcodeRelease"])}.</p>\n')
    folder = f'/data/sold-prices/history/{d["month"]}'
    lines = ['<div class="table-wrap"><table><thead><tr><th>Area</th><th class="num">Districts</th><th class="num">Rows</th>'
             '<th>CSV</th><th>JSON</th></tr></thead>', '<tbody>']
    for entry in d['areas']:
        a = entry['area']
        csv_name, json_name = f'history_{a}.csv', f'history_{a}.json'
        lines.append(f'<tr><td>{e(a)}</td><td class="num">{entry["districts"]:,}</td><td class="num">{entry["rows"]:,}</td>'
                     f'<td><a href="{folder}/{csv_name}">{csv_name}</a> ({_size(len(history.files[csv_name]))})</td>'
                     f'<td><a href="{folder}/{json_name}">{json_name}</a> ({_size(len(history.files[json_name]))})</td></tr>')
    lines.append('</tbody></table></div>')
    downloads = '\n'.join(lines) + '\n'
    rows = ['<div class="table-wrap"><table><thead><tr><th>Build month</th><th>Built</th><th>Years to</th><th class="num">Areas</th>'
            '<th class="num">Rows</th><th>Index</th></tr></thead>', '<tbody>']
    for m in months:
        rows.append(f'<tr><td>{e(m["month"])}</td><td>{e(m["builtAt"][:10])}</td><td>{m["lastYear"]}</td><td class="num">{m["areas"]}</td>'
                    f'<td class="num">{m["rows"]:,}</td><td><a href="/data/sold-prices/history/{e(m["month"])}/{INDEX_FILE}">{INDEX_FILE}</a></td></tr>')
    rows.append('</tbody></table></div>')
    archive = '\n'.join(rows) + '\n'
    attribution = ''.join(f'<p class="attribution">{e(a)}</p>\n' for a in d['attribution'])
    method = f'<p class="method">{e(d["method"])}</p>\n'
    return {'summary': summary, 'downloads': downloads, 'archive': archive, 'attribution': attribution, 'method': method}


@dataclass(frozen=True)
class Plan:
    files: list[tuple[Path, bytes]]
    page: str
    sitemap: str
    done: list[str]


def plan_publish(root: Path, history: History, today: str) -> Plan:
    """Everything the publish writes, worked out in memory. Raises CheckFailed or TemplateBroken before anything is written."""
    base = root / OUT
    folder = base / history.month
    files: list[tuple[Path, bytes]] = []
    done: list[str] = []
    if folder.exists():
        same = (all((folder / name).exists() and (folder / name).read_bytes() == data for name, data in history.files.items())
                and {p.name for p in folder.iterdir()} == set(history.files))
        if not same:
            raise CheckFailed(6, f'the archive folder for {history.month} exists and differs: an archive is never rewritten '
                                 f'(a person decides)', refused=False)
        done.append(f'the {history.month} archive is already as fetched')
    else:
        for name, data in history.files.items():
            files.append((folder / name, data))
        done.append(f'archived {len(history.files)} files under {history.month}/')
    files.append((base / LATEST_INDEX, history.files[INDEX_FILE]))
    done.append(f'wrote {LATEST_INDEX}')
    months = archived_months(root)
    if not any(m['month'] == history.month for m in months):
        months.append({'month': history.month, 'builtAt': history.index['builtAt'], 'lastYear': history.index['lastYear'],
                       'areas': len(history.area_files), 'rows': history.rows})
        months.sort(key=lambda m: m['month'], reverse=True)
    try:
        page = (root / PAGE).read_text(encoding='utf-8')
        sitemap = (root / SITEMAP).read_text(encoding='utf-8')
    except OSError:
        raise TemplateBroken('the page or sitemap is missing') from None
    for name, content in render_regions(history, months).items():
        page = _region(page, name, content)
    for statement in history.index['attribution']:      # the attribution is shown on the page
        if f'<p class="attribution">{html.escape(statement)}</p>' not in page:
            raise CheckFailed(8, 'the attribution is not on the page')
    if f'<p class="method">{html.escape(history.index["method"])}</p>' not in page:
        raise CheckFailed(8, 'the method is not on the page')
    pattern = re.compile(r'(<loc>' + re.escape(PAGE_URL) + r'</loc>\s*<lastmod>)[0-9-]{10}(</lastmod>)')
    if len(pattern.findall(sitemap)) != 1:
        raise TemplateBroken('sitemap.xml has no single entry for the page')
    done.append('updated sold-prices/history/index.html and its sitemap lastmod')
    return Plan(files, page, pattern.sub(rf'\g<1>{today}\g<2>', sitemap), done)


def write_plan(root: Path, plan: Plan) -> None:
    for path, data in plan.files:
        path.parent.mkdir(parents=True, exist_ok=True)
        _replace(path, data)
    _replace(root / PAGE, plan.page.encode('utf-8'))
    _replace(root / SITEMAP, plan.sitemap.encode('utf-8'))


def load_incoming(root: Path) -> dict[str, bytes]:
    """HS_STATE.json, history_index.json and the area files the folder holds (the index decides which are used)."""
    folder = root / INCOMING
    raws: dict[str, bytes] = {}
    for path in sorted(folder.iterdir()):
        if path.is_file() and (path.name in (STATE_FILE, INDEX_FILE) or re.fullmatch(r'history_[A-Z]{1,2}\.(?:json|csv)', path.name)):
            raws[path.name] = path.read_bytes()
    return raws


def main(argv: list[str] | None = None, *, root: Path = REPO, today: str | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='the checks only; writes nothing')
    mode.add_argument('--publish', action='store_true')
    parser.add_argument('--first-publish', action='store_true', help='only when no history is live yet')
    args = parser.parse_args(argv)
    if not is_this_repo(root):
        print(json.dumps({'status': 'refused', 'code': 'not-the-data-yappman-repo'}))
        return 2
    try:
        raws = load_incoming(root)
    except OSError:
        print(json.dumps({'status': 'refused', 'code': 'incoming-files-missing', 'folder': str(INCOMING)}))
        return 2
    live = None
    try:
        live = live_history(root)
        history = check_history(raws, live, args.first_publish)
        if live is not None and live['month'] == history.month and live['builtAt'] == history.state['builtAt']:
            print(json.dumps({'status': 'nothing-new', 'month': history.month, 'builtAt': history.state['builtAt']}))
            return 0
        plan = plan_publish(root, history, today or datetime.now(UTC).date().isoformat())
    except CheckFailed as failure:
        print(json.dumps({'status': 'refused' if failure.refused else 'held', 'check': failure.check,
                          'reason': str(failure), 'live': live}))
        return 2 if failure.refused else 3
    except TemplateBroken as broken:
        print(json.dumps({'status': 'held', 'code': 'template-broken', 'reason': str(broken)}))
        return 3
    sizes = [len(data) for data in history.files.values()]      # what the repo will hold for this build (one copy)
    summary = {'month': history.month, 'builtAt': history.state['builtAt'], 'rows': history.rows, 'areas': len(history.area_files),
               'files': len(sizes), 'totalBytes': sum(sizes), 'largestBytes': max(sizes), 'live': live}
    if args.check:
        print(json.dumps({'status': 'checks-passed', **summary, 'wouldDo': plan.done}))
        return 0
    write_plan(root, plan)
    print(json.dumps({'status': 'published', **summary, 'done': plan.done}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
