"""/this-week/: a few dated rows from our own free published data (no network, no token).

Reads only files already public in this repo and fills the marked regions of this-week/index.html:

    python -I -B docs/release/this_week_site.py --check      # the checks only, writes nothing
    python -I -B docs/release/this_week_site.py --publish    # the page and its sitemap lastmod

- UK Online Shelf-Price Index (data/uk-shelf-price-index.json): the latest vintage's headline level and week-on-week
  change, and the three largest moves up and down among categories with at least MIN_MATCHED matched products.
- UK Christmas basket (data/christmas-basket.json): the latest week's totals per retailer for the items priced in
  common, and a like-for-like comparison with the week before over the item NUMBERS common in both weeks (the count
  alone is not enough: an item can leave and another join). Each week's set of common items (priced at all four
  retailers, not optional) must give back that week's own commonItems and commonTotal, or the page is held.
- Monthly tables (data/sold-prices/ and data/rental-yield/ latest files): shown only in a week when a new table was
  built (builtAt within NEW_TABLE_DAYS of the run day); otherwise "no new monthly table this week". Each shown table
  carries its caveats (sentences that stand on its page or in its method text, compared by a test) and the attribution
  lines copied at build time from the attribution region of its own page, so the licence notices always match.
- Category moves: the TOP_MOVES largest, plus every category tied with the last one shown (ties are not cut).
- A source whose latest date is more than FRESH_DAYS old says "not updated this week" instead of showing figures.
- The pointers to the paid Actors are sentences that already stand on public pages (a test compares each with its
  source page). No prices, no new claims. The AU index has no site copy of its data, so it is not on the page.

Every number is re-read from the source file; nothing is written unless every check passes. The helpers of
district_table_site.py are reused and not changed.

Exit codes: 0 published / checks passed; 2 refused (usage, wrong folder); 3 a check failed, nothing written.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import statistics
import sys
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import district_table_site as dts  # noqa: E402  (the reviewed helpers; nothing in it is changed)

CheckFailed, TemplateBroken = dts.CheckFailed, dts.TemplateBroken

FRESH_DAYS = 8          # a source older than this says "not updated this week"
NEW_TABLE_DAYS = 7      # a monthly table built within this many days is "new this week"
MIN_MATCHED = 100       # a category move is shown only with at least this many matched products
TOP_MOVES = 3
UK_JSON = Path('data/uk-shelf-price-index.json')
BASKET_JSON = Path('data/christmas-basket.json')
SOLD_JSON = Path('data/sold-prices/district-medians-latest.json')
YIELD_JSON = Path('data/rental-yield/rental-yield-latest.json')
PAGE = Path('this-week/index.html')
PAGE_URL = 'https://data.yappman.com/this-week/'
RETAILERS = ('tesco', 'sainsburys', 'asda', 'aldi')
RETAILER_NAMES = {'tesco': 'Tesco', 'sainsburys': "Sainsbury's", 'asda': 'Asda', 'aldi': 'Aldi'}
VINTAGE_RE = re.compile(r'20[0-9]{2}-W(?:0[1-9]|[1-4][0-9]|5[0-3])')
CLASS_RE = re.compile(r'[a-z]+(?:-[a-z]+)*')
UK_ATTRIBUTION = 'Yappman Data, UK Online Shelf-Price Index, CC BY 4.0, https://data.yappman.com/shelf-price-index/'
BASKET_ATTRIBUTION = 'Yappman Data, UK Christmas Dinner Basket 2026, CC BY 4.0, https://data.yappman.com/christmas-basket/'
UTM = 'utm_source=data.yappman.com&amp;utm_medium=referral&amp;utm_campaign=this-week'
# The pointer sentences, word for word as they stand on the source pages (a test compares each with its page).
POINTERS = (
    ('christmas-basket/index.html',
     'Product-level shelf prices for these retailers can be read on demand with the '
     '<a href="https://apify.com/yappman/uk-supermarket-price-scraper?' + UTM + '">UK Supermarket Price Scraper</a>, '
     'a pay-per-event Actor on the Apify Store.'),
    ('sold-prices/index.html',
     'For current asking prices in a district, and a free rental yield summary by outcode, use the '
     '<a href="https://apify.com/yappman/uk-property-listings?' + UTM + '">UK Property Listings Actor</a>.'),
    ('rental-yield/index.html',
     'For outcode and bedroom level from current listings, use the '
     '<a href="https://apify.com/yappman/uk-property-listings?' + UTM + '">UK Property Listings Actor</a>&rsquo;s rentalYield summary.'),
)
# The caveats shown with the rental-yield table, word for word as they stand on its page (a test compares each with it).
YIELD_CAVEATS = (
    'It is gross, before costs, voids, tax and finance, and it is not advice. The rent is a mean and the price a median, '
    'and the homes rented and the homes sold differ, so these are area averages, not a valuation.',
    'The rents come from the ONS Price Index of Private Rents (PIPR).',
    'PIPR figures are statistics in development and are not seasonally adjusted.',
)
# A sentence from the sold-prices table's own method text (the method field of its JSON; a test compares it).
SOLD_REVISION = 'The newest months are revised as late registrations arrive.'
SOURCE_PAGES = {'sold-prices': Path('sold-prices/index.html'), 'rental-yield': Path('rental-yield/index.html')}
ATTRIBUTION_RE = re.compile(r'<p class="attribution">[^<>]+</p>')


def _read_json(root: Path, relative: Path, what: str) -> Any:
    try:
        return json.loads((root / relative).read_bytes().decode('utf-8'), object_pairs_hook=dts._no_repeats)
    except (OSError, UnicodeDecodeError, ValueError):
        raise CheckFailed(1, f'{what} ({relative}) cannot be read as strict JSON') from None


def _num(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _day(text: Any, what: str) -> date:
    try:
        return datetime.fromisoformat(str(text).replace('Z', '+00:00')).date()
    except ValueError:
        raise CheckFailed(2, f'{what} is not a real date') from None


def _round(value: float | int, places: int) -> str:
    quantum = Decimal(1).scaleb(-places)
    return f'{Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP):,}'


def _signed(value: float, places: int = 2) -> str:
    text = _round(abs(value), places)
    if Decimal(text.replace(',', '')) == 0:      # no sign on a figure that rounds to zero (a sum of floats can be -1e-15)
        return text
    return ('+' if value > 0 else '-') + text


# --- the figures --------------------------------------------------------------------------------------------------

def _top(ordered: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The first TOP_MOVES, plus every later one tied with the last of them (the same week-on-week value)."""
    if len(ordered) <= TOP_MOVES:
        return ordered
    cut = ordered[TOP_MOVES - 1]['weekOnWeekPct']
    return ordered[:TOP_MOVES] + [r for r in ordered[TOP_MOVES:] if r['weekOnWeekPct'] == cut]


def uk_figures(records: Any, today: date) -> dict[str, Any]:
    if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
        raise CheckFailed(2, 'the UK index file is not a list of records')
    heads = [r for r in records if r.get('recordType') == 'headline' and r.get('status') == 'ok']
    vintages = sorted({r['vintage'] for r in heads if isinstance(r.get('vintage'), str) and VINTAGE_RE.fullmatch(r['vintage'])})
    if not vintages:
        raise CheckFailed(2, 'the UK index file has no headline record')
    vintage = vintages[-1]
    head = [r for r in heads if r['vintage'] == vintage]
    if len(head) != 1 or not _num(head[0].get('level')) or not _num(head[0].get('weekOnWeekPct')) or head[0]['level'] <= 0:
        raise CheckFailed(2, 'the latest UK headline record is missing or malformed')
    published = _day(head[0].get('publishedAt'), 'the UK publishedAt')
    classes = []
    for r in records:
        if r.get('recordType') == 'class' and r.get('vintage') == vintage and r.get('status') == 'ok':
            if not (isinstance(r.get('class'), str) and CLASS_RE.fullmatch(r['class'])) or not _num(r.get('weekOnWeekPct')) \
                    or not _num(r.get('level')) or type(r.get('matched')) is not int:
                raise CheckFailed(2, 'a UK category record is malformed')
            if r['matched'] >= MIN_MATCHED:
                classes.append(r)
    up = _top(sorted((r for r in classes if r['weekOnWeekPct'] > 0), key=lambda r: (-r['weekOnWeekPct'], r['class'])))
    down = _top(sorted((r for r in classes if r['weekOnWeekPct'] < 0), key=lambda r: (r['weekOnWeekPct'], r['class'])))
    return {'vintage': vintage, 'published': published, 'fresh': 0 <= (today - published).days <= FRESH_DAYS,
            'level': head[0]['level'], 'wow': head[0]['weekOnWeekPct'], 'up': up, 'down': down}


def basket_figures(document: Any, today: date) -> dict[str, Any]:
    weeks = document.get('weeks') if isinstance(document, dict) else None
    if not isinstance(weeks, list) or not weeks:
        raise CheckFailed(2, 'the basket file has no weeks')

    def week(w: Any) -> dict[str, Any]:
        if not isinstance(w, dict) or not isinstance(w.get('week'), str) or not VINTAGE_RE.fullmatch(w['week']) \
                or type(w.get('commonItems')) is not int or not isinstance(w.get('commonTotal'), dict) \
                or set(w['commonTotal']) != set(RETAILERS) or not all(_num(w['commonTotal'][k]) and w['commonTotal'][k] > 0 for k in RETAILERS):
            raise CheckFailed(2, 'a basket week is malformed')
        common = _common_items(w)
        # The set of common items must give back the week's own count and totals, or the file is not understood.
        if len(common) != w['commonItems'] or any(abs(sum(p[k] for p in common.values()) - w['commonTotal'][k]) > 0.005 for k in RETAILERS):
            raise CheckFailed(2, f'the basket items of {w["week"]} do not add up to its common totals')
        return {'week': w['week'], 'asOf': _day(w.get('asOf'), 'the basket asOf'), 'items': w['commonItems'], 'totals': w['commonTotal'],
                'common': common}
    latest = week(weeks[-1])
    previous = week(weeks[-2]) if len(weeks) > 1 else None
    return {'latest': latest, 'previous': previous, 'fresh': 0 <= (today - latest['asOf']).days <= FRESH_DAYS}


def _common_items(w: dict[str, Any]) -> dict[int, dict[str, float]]:
    """The items priced at all four retailers and not optional (the basket page's rule for its headline total), by item number."""
    items = w.get('items')
    if not isinstance(items, list) or not all(isinstance(i, dict) and type(i.get('n')) is int for i in items) \
            or len({i['n'] for i in items}) != len(items):
        raise CheckFailed(2, 'the basket items are malformed')
    common = {}
    for i in items:
        flags = i.get('flags') or {}
        if not isinstance(flags, dict) or not all(isinstance(v, list) for v in flags.values()):
            raise CheckFailed(2, 'the basket item flags are malformed')
        if all(_num(i.get(k)) and i[k] > 0 for k in RETAILERS) and not any('optional' in flags.get(k, []) for k in RETAILERS):
            common[i['n']] = {k: i[k] for k in RETAILERS}
    return common


def monthly_figures(document: Any, today: date, kind: str) -> dict[str, Any]:
    rows = document.get('rows') if isinstance(document, dict) else None
    if not isinstance(rows, list) or not rows or not isinstance(document.get('builtAt'), str) or not dts._is_month(document.get('month')):
        raise CheckFailed(2, f'the {kind} table file is malformed')
    built = _day(document['builtAt'], f'the {kind} builtAt')
    if not (dts._is_month(document.get('periodFrom')) and dts._is_month(document.get('periodTo'))) \
            or type(document.get('lagMonths')) is not int or not 0 < document['lagMonths'] < 13:
        raise CheckFailed(2, f'the {kind} table has no well-formed period or lag')
    if kind == 'sold-prices':
        key, shown = 'median12m', [r for r in rows if r.get('propertyType') == 'all']
        ids = {r.get('district') for r in shown}
    else:
        key, shown = 'grossYieldPct', [r for r in rows if r.get('propertyType') == 'all']
        ids = {r.get('authorityCode') for r in shown}
    values = [r[key] for r in shown if r.get(key) is not None]
    if not values or not all(_num(v) and v > 0 for v in values):
        raise CheckFailed(2, f'the {kind} table has no usable all-homes figures')
    new = 0 <= (today - built).days <= NEW_TABLE_DAYS
    return {'month': document['month'], 'built': built, 'new': new, 'places': len(ids), 'withFigure': len(values),
            'median': statistics.median(values), 'from': document['periodFrom'], 'to': document['periodTo'],
            'lag': document['lagMonths']}


def attribution(root: Path, kind: str) -> str:
    """The attribution lines of the table's own page, copied as they stand there (plain text paragraphs only)."""
    try:
        text = (root / SOURCE_PAGES[kind]).read_text(encoding='utf-8').replace('\r\n', '\n')
    except OSError:
        raise TemplateBroken(f'the {kind} page is missing') from None
    start, end = '<!-- district-table:attribution -->\n', '\n<!-- /district-table:attribution -->'
    if text.count(start) != 1 or text.count(end) != 1:
        raise TemplateBroken(f'the {kind} page has no single attribution region')
    lines = text.split(start)[1].split(end)[0].split('\n')
    if not all(ATTRIBUTION_RE.fullmatch(line) for line in lines) or not any('HM Land Registry' in line for line in lines):
        raise TemplateBroken(f'the {kind} attribution region is not the expected lines')
    return ''.join(lines)


# --- the page -----------------------------------------------------------------------------------------------------

def _moves(label: str, moves: list[dict[str, Any]]) -> str:
    if not moves:
        return f'<p>{label}: none this week.</p>'
    rows = ''.join(f'<tr><td>{html.escape(r["class"].replace("-", " "))}</td><td>{_signed(r["weekOnWeekPct"])}%</td>'
                   f'<td>{r["matched"]:,}</td></tr>' for r in moves)
    return (f'<p>{label}:</p><div class="table-wrap"><table><thead><tr><th>Category</th><th>Week on week</th>'
            f'<th>Matched products</th></tr></thead><tbody>{rows}</tbody></table></div>')


def render(uk: dict[str, Any], basket: dict[str, Any], sold: dict[str, Any], rent: dict[str, Any], today: date,
           notices: dict[str, str]) -> dict[str, str]:
    e = html.escape
    if uk['fresh']:
        ukhtml = (f'<p>Vintage {e(uk["vintage"])}, published {uk["published"].isoformat()}: the headline level is '
                  f'{_round(uk["level"], 2)}, {_signed(uk["wow"])}% on the week before. Source: '
                  f'<a href="/shelf-price-index/">UK Online Shelf-Price Index</a> (CC BY 4.0). Shelf prices only; not CPI.</p>'
                  + _moves(f'Largest category rises (categories with at least {MIN_MATCHED} matched products; '
                           'categories tied at the cut-off are all shown)', uk['up'])
                  + _moves('Largest category falls', uk['down'])
                  + f'<p class="attribution">{e(UK_ATTRIBUTION)}</p>')
    else:
        ukhtml = (f'<p>Not updated this week: the latest vintage on <a href="/shelf-price-index/">the UK index page</a> is '
                  f'{e(uk["vintage"])}, published {uk["published"].isoformat()}.</p>')
    b, p = basket['latest'], basket['previous']
    if basket['fresh']:
        cells = ''.join(f'<tr><td>{RETAILER_NAMES[k]}</td><td>&pound;{_round(b["totals"][k], 2)}</td></tr>' for k in RETAILERS)
        compare = ''
        both = sorted(set(b['common']) & set(p['common'])) if p is not None else []
        if both:
            # Like for like: both weeks' totals over the same items only (an item in one week alone is left out).
            now = {k: sum(b['common'][n][k] for n in both) for k in RETAILERS}
            before = {k: sum(p['common'][n][k] for n in both) for k in RETAILERS}
            diffs = ''.join(f'<li>{RETAILER_NAMES[k]}: {_signed(now[k] - before[k], 2)} '
                            f'({_signed((now[k] / before[k] - 1) * 100, 1)}%)</li>' for k in RETAILERS)
            if set(b['common']) == set(p['common']):
                compare = f'<p>Against {e(p["week"])} (the same {len(both)} items priced in common), in pounds:</p><ul>{diffs}</ul>'
            else:
                compare = (f'<p>Against {e(p["week"])}, like for like over the {len(both)} items priced at all four retailers in '
                           f'both weeks (items priced in common in only one of the two weeks are left out), in pounds:</p><ul>{diffs}</ul>')
        elif p is not None:
            compare = f'<p>No comparison with {e(p["week"])}: no item was priced in common in both weeks.</p>'
        bhtml = (f'<p>{e(b["week"])}, as of {b["asOf"].isoformat()}: the {b["items"]} items priced at all four retailers, '
                 f'total per retailer. Source: <a href="/christmas-basket/">UK Christmas dinner basket 2026</a> (CC BY 4.0).</p>'
                 f'<div class="table-wrap"><table><thead><tr><th>Retailer</th><th>Total for the common items</th></tr></thead>'
                 f'<tbody>{cells}</tbody></table></div>{compare}<p class="attribution">{e(BASKET_ATTRIBUTION)}</p>')
    else:
        bhtml = (f'<p>Not updated this week: the latest week on <a href="/christmas-basket/">the basket page</a> is '
                 f'{e(b["week"])}, as of {b["asOf"].isoformat()}.</p>')
    parts = []
    if sold['new']:
        parts.append(f'<p><a href="/sold-prices/">Median sold prices by postcode district</a>: new table for {e(sold["month"])}. '
                     f'{sold["places"]:,} districts, of which {sold["withFigure"]:,} have a 12-month median for all homes; '
                     f'the median of those medians is &pound;{_round(sold["median"], 0)}. The sales are standard sales in England and '
                     f'Wales by transfer date, from {e(sold["from"])} to {e(sold["to"])}, ending {sold["lag"]} months before the table month to allow for registration. '
                     f'{SOLD_REVISION}</p>' + notices['sold-prices'])
    if rent['new']:
        parts.append(f'<p><a href="/rental-yield/">Gross rental yield by local authority</a>: new table for {e(rent["month"])}. '
                     f'{rent["places"]:,} authorities, of which {rent["withFigure"]:,} have an all-homes yield; '
                     f'the median of those yields is {_round(rent["median"], 1)}%. '
                     + ' '.join(YIELD_CAVEATS) + '</p>' + notices['rental-yield'])
    mhtml = ''.join(parts) if parts else '<p>No new monthly table this week.</p>'
    pointers = ''.join(f'<li>{sentence}</li>' for _, sentence in POINTERS)
    summary = f'<p>Updated {today.isoformat()}. Every figure below is read from a free file already published on this site.</p>\n'
    return {'summary': summary, 'uk': ukhtml + '\n', 'basket': bhtml + '\n', 'monthly': mhtml + '\n', 'pointers': f'<ul>{pointers}</ul>\n'}


def build(root: Path, today: date) -> tuple[str, str, dict[str, Any]]:
    uk = uk_figures(_read_json(root, UK_JSON, 'the UK index'), today)
    basket = basket_figures(_read_json(root, BASKET_JSON, 'the basket'), today)
    sold = monthly_figures(_read_json(root, SOLD_JSON, 'the sold-prices table'), today, 'sold-prices')
    rent = monthly_figures(_read_json(root, YIELD_JSON, 'the rental-yield table'), today, 'rental-yield')
    try:
        page = (root / PAGE).read_text(encoding='utf-8')
        sitemap = (root / dts.SITEMAP).read_text(encoding='utf-8')
    except OSError:
        raise TemplateBroken('the page or sitemap is missing') from None
    notices = {kind: attribution(root, kind) for kind, table in (('sold-prices', sold), ('rental-yield', rent)) if table['new']}
    for name, content in render(uk, basket, sold, rent, today, notices).items():
        page = dts._region(page, name, content)
    pattern = re.compile(r'(<loc>' + re.escape(PAGE_URL) + r'</loc>\s*<lastmod>)[0-9-]{10}(</lastmod>)')
    if len(pattern.findall(sitemap)) != 1:
        raise TemplateBroken('sitemap.xml has no single entry for the page')
    facts = {'uk': uk['vintage'], 'ukFresh': uk['fresh'], 'basket': basket['latest']['week'], 'basketFresh': basket['fresh'],
             'newSoldTable': sold['new'], 'newYieldTable': rent['new']}
    return page, pattern.sub(rf'\g<1>{today.isoformat()}\g<2>', sitemap), facts


def main(argv: list[str] | None = None, *, root: Path = dts.REPO, today: date | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='the checks only; writes nothing')
    mode.add_argument('--publish', action='store_true')
    args = parser.parse_args(argv)
    if not dts.is_this_repo(root):
        print(json.dumps({'status': 'refused', 'code': 'not-the-data-yappman-repo'}))
        return 2
    try:
        page, sitemap, facts = build(root, today or datetime.now(UTC).date())
    except CheckFailed as failure:
        print(json.dumps({'status': 'held', 'check': failure.check, 'reason': str(failure)}))
        return 3
    except TemplateBroken as broken:
        print(json.dumps({'status': 'held', 'code': 'template-broken', 'reason': str(broken)}))
        return 3
    if args.check:
        print(json.dumps({'status': 'checks-passed', **facts}))
        return 0
    dts._replace(root / PAGE, page.encode('utf-8'))
    dts._replace(root / dts.SITEMAP, sitemap.encode('utf-8'))
    print(json.dumps({'status': 'published', **facts}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
