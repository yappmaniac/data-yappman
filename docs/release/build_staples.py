#!/usr/bin/env python3
"""Free staple files for the Data Website: weekly pooled statistics for the 20 staples of the UK daily basket.

Writes two static files, from the public daily-basket CSV and the staples definition (tools/basket/uk-staples.json of the Actor repo):

  data/staples-weekly.json              per staple and ISO week: how many products, and the median posted unit price pooled over them
  data/staple-price-moves-weekly.json   per staple and ISO week: how many of the matched products rose, fell or stayed the same

Rules (they are what keeps a file from showing one product's price):
  - Pooled over the products of a staple at Tesco, Sainsbury's, Asda and Aldi. No retailer name, product id, product name or URL is written.
  - A product counts in a week only if it was seen on at least --min-days days of that week. A week with fewer than --min-products
    counted products is left out and listed under "withheld".
  - Both --min-products and --min-days are REQUIRED arguments with no default: they are decisions, not settings.
  - The unit price is the one the retailer posts. 100g becomes kg and 100ml becomes l (x10). A staple uses the unit family held by most
    of its product-weeks (kg, l or item); products on another family are left out and counted.
  - No network, no clock, no token. Same inputs and arguments give byte-identical files.

Usage:
  python docs/release/build_staples.py --basket FILE.csv --staples uk-staples.json --min-products N --min-days N [--out-dir DIR]
  python docs/release/build_staples.py --check [--out-dir DIR]     (validates the two committed files; needs no inputs)
"""
import argparse
import csv
import datetime
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from statistics import median, median_low

OUT_WEEKLY = 'staples-weekly.json'
OUT_MOVES = 'staple-price-moves-weekly.json'
WEEK_RE = re.compile(r'^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$')
FAMILY_FACTOR = {'kg': (Decimal(1), 'kg'), '100g': (Decimal(10), 'kg'), 'l': (Decimal(1), 'l'), '100ml': (Decimal(10), 'l'), 'each': (Decimal(1), 'item')}
BASIS_LABEL = {'kg': 'GBP per kg', 'l': 'GBP per litre', 'item': 'GBP per item'}
CENT = Decimal('0.01')
NOTE = ('Posted online shelf prices, not prices paid, of the products in each staple, pooled over Tesco, Sainsbury\'s, Asda and Aldi from the public UK daily basket. '
        'Unit prices as the retailers post them. Pooled figures only: no retailer, product or link is given. Not CPI and not a price comparison; '
        'weeks with too few products are left out. If the basket was read more than once on a day, the latest read counts. '
        'Credit: Yappman Data, UK Supermarket Prices: Daily 212-Item Basket, CC BY 4.0. Retailer names are used only to describe the source of public product information; '
        'no affiliation, endorsement or partnership is claimed.')
LICENSE = 'https://creativecommons.org/licenses/by/4.0/'
FORBIDDEN_KEYS ={'retailer', 'retailers', 'retailerProductId', 'url', 'ean', 'brand', 'matchKey', 'product', 'products', 'price', 'prices'}


class BuildError(Exception):
    pass


def iso_week(day):
    y, w, _ = day.isocalendar()
    return f'{y}-W{w:02d}'


def week_monday(week):
    y, w = int(week[:4]), int(week[6:])
    return datetime.date.fromisocalendar(y, w, 1)


def q2(x):
    return float(Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP))


def slug(query):
    return re.sub(r'[^a-z0-9]+', '-', query.lower()).strip('-')


def parse_decimal(text):
    try:
        v = Decimal(text)
    except (InvalidOperation, TypeError):
        return None
    return v if v.is_finite() else None


def read_inputs(basket_path, staples_path):
    with open(staples_path, encoding='utf-8') as f:
        st = json.load(f)
    for k in ('queries', 'products', 'version'):
        if k not in st:
            raise BuildError(f'staples file has no "{k}"')
    owner = {}
    for p in st['products']:
        key = (p['retailer'], str(p['retailerProductId']))
        if key in owner and owner[key] != p['query']:
            raise BuildError(f'product {key} is in two staples')
        owner[key] = p['query']
    unknown = sorted({q for q in owner.values()} - set(st['queries']))
    if unknown:
        raise BuildError(f'products refer to staples not in "queries": {unknown}')
    with open(basket_path, encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))
    for col in ('retailer', 'retailerProductId', 'price', 'scrapedAt'):
        if rows and col not in rows[0]:
            raise BuildError(f'basket file has no column "{col}"')
    return st, owner, rows


def build(basket_path, staples_path, min_products, min_days):
    if min_products < 1 or min_days < 1:
        raise BuildError('--min-products and --min-days must be at least 1')
    st, owner, rows = read_inputs(basket_path, staples_path)
    # (staple, product key, week) -> {day: [prices]} and unit values by day
    price_days = defaultdict(lambda: defaultdict(list))
    unit_days = defaultdict(lambda: defaultdict(list))   # -> {day: [(family, value)]}
    skipped = Counter()
    latest = {}   # (staple, product key, week), day -> (scrapedAt, price, unit)
    for r in rows:
        key = (r['retailer'], str(r['retailerProductId']))
        q = owner.get(key)
        if q is None:
            skipped['not in the staples file'] += 1
            continue
        try:
            day = datetime.date.fromisoformat(r['scrapedAt'][:10])
        except ValueError:
            raise BuildError(f'bad scrapedAt "{r["scrapedAt"][:25]}"')
        price = parse_decimal(r['price'])
        if price is None or price <= 0:
            skipped['no usable price'] += 1
            continue
        k = (q, key, iso_week(day))
        uv, um = parse_decimal(r.get('unitPrice/value', '')), (r.get('unitPrice/measure') or '').strip()
        unit = None
        if uv is not None and uv > 0 and um in FAMILY_FACTOR:
            factor, family = FAMILY_FACTOR[um]
            unit = (family, uv * factor)
        # a product has one value per day: if the basket was read more than once that day, the LATEST run counts
        # (the same timestamp twice: the lower price), so a repeated run cannot pull a day's value either way
        prev = latest.get((k, day))
        if prev is not None:
            skipped['repeat run on the same day (one dropped)'] += 1
        if prev is None or (r['scrapedAt'], -price) > (prev[0], -prev[1]):
            latest[(k, day)] = (r['scrapedAt'], price, unit)
    for (k, day), (_, price, unit) in latest.items():
        price_days[k][day].append(price)
        if unit is not None:
            unit_days[k][day].append(unit)

    # one value per product-week: low median of the daily values, only if seen on enough days
    prod_price = {}   # (q, key, week) -> Decimal
    prod_unit = {}    # (q, key, week) -> (family, Decimal)
    for k, days in price_days.items():
        if len(days) < min_days:
            continue
        prod_price[k] = median_low([median_low(v) for _, v in sorted(days.items())])
        fam = Counter(f for d in unit_days[k].values() for f, _ in d)
        if fam:
            family = sorted(fam.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            vals = [median_low([v for f, v in d if f == family]) for _, d in sorted(unit_days[k].items()) if any(f == family for f, _ in d)]
            prod_unit[k] = (family, median_low(vals))

    weeks_seen = sorted({k[2] for k in price_days})
    staples_out, moves_out = [], []
    for q in st['queries']:
        # the staple's unit family: the one held by most of its product-weeks
        fam_count = Counter(prod_unit[k][0] for k in prod_unit if k[0] == q)
        series, withheld, mseries, mwithheld = [], [], [], []
        basis = sorted(fam_count.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if fam_count else None
        other = len({k[1] for k in prod_unit if k[0] == q and prod_unit[k][0] != basis}) if basis else 0
        no_unit = len({k[1] for k in prod_price if k[0] == q and k not in prod_unit})
        for w in weeks_seen:
            vals = [prod_unit[k][1] for k in prod_unit if k[0] == q and k[2] == w and prod_unit[k][0] == basis]
            seen_any = any(k[0] == q and k[2] == w for k in price_days)
            if len(vals) >= min_products:
                series.append({'week': w, 'n': len(vals), 'medianUnitPrice': q2(median(vals))})
            elif seen_any:
                withheld.append(w)
        for w in weeks_seen:
            prev = (week_monday(w) - datetime.timedelta(days=7))
            pw = iso_week(prev)
            cur = {k[1]: v for k, v in prod_price.items() if k[0] == q and k[2] == w}
            old = {k[1]: v for k, v in prod_price.items() if k[0] == q and k[2] == pw}
            both = sorted(set(cur) & set(old))
            if not old:
                continue
            if len(both) >= min_products:
                mseries.append({'week': w, 'matched': len(both), 'rose': sum(cur[p] > old[p] for p in both),
                                'fell': sum(cur[p] < old[p] for p in both), 'unchanged': sum(cur[p] == old[p] for p in both)})
            else:
                mwithheld.append(w)
        base = {'id': slug(q), 'name': q[:1].upper() + q[1:]}
        staples_out.append({**base, 'basis': BASIS_LABEL.get(basis, 'none'),
                            'firstWeek': series[0]['week'] if series else None, 'lastWeek': series[-1]['week'] if series else None,
                            'productsOnOtherUnit': other + no_unit, 'withheld': withheld, 'series': series})
        moves_out.append({**base, 'withheld': mwithheld, 'weeks': mseries})
    definition = {
        'source': 'UK daily 212-item basket (public dataset), CC BY 4.0',
        'staplesFile': f'uk-staples.json version {st["version"]}' + (f', built {st["builtAt"]}' if st.get('builtAt') else ''),
        'firstDay': min(min(days) for days in price_days.values()).isoformat() if price_days else None,
        'lastDay': max(max(days) for days in price_days.values()).isoformat() if price_days else None,
        'weekRule': f'A product counts in an ISO week if seen on at least {min_days} days of it; its value is the low median of its daily values. '
                    f'A week needs at least {min_products} counted products.',
        'minProducts': min_products, 'minDays': min_days,
        'unitRule': 'Unit price as posted; 100g and 100ml converted to kg and l; each staple uses its most common unit; other products left out.',
    }
    weekly = {'schema': 1, 'note': NOTE, 'notCpi': True, 'license': LICENSE, 'definition': definition, 'staples': staples_out}
    moves = {'schema': 1, 'note': NOTE.replace('Unit prices as the retailers post them.', 'Counts of products whose posted shelf price rose, fell or stayed the same on the week before.'),
             'notCpi': True, 'license': LICENSE, 'definition': definition, 'staples': moves_out}
    return weekly, moves, skipped


def dump(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False) + '\n'


def write_atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.staples-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def walk_keys(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from walk_keys(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk_keys(v)


def check_files(out_dir):
    """Problems found in the two committed files (an empty list means they are well formed)."""
    problems = []
    docs = {}
    for name in (OUT_WEEKLY, OUT_MOVES):
        path = os.path.join(out_dir, name)
        try:
            with open(path, encoding='utf-8', newline='') as f:
                raw = f.read()
            docs[name] = json.loads(raw)
        except (OSError, ValueError) as e:
            problems.append(f'{name}: cannot read ({e.__class__.__name__})')
            continue
        if '\r' in raw:
            problems.append(f'{name}: has CR characters')
        if raw != dump(docs[name]):
            problems.append(f'{name}: is not in the canonical layout')
        bad = FORBIDDEN_KEYS & set(walk_keys(docs[name]))
        if bad:
            problems.append(f'{name}: has forbidden keys {sorted(bad)}')
        if docs[name].get('schema') != 1 or docs[name].get('notCpi') is not True:
            problems.append(f'{name}: schema must be 1 and notCpi true')
    for name, d in docs.items():
        df = d.get('definition', {})
        mp, md = df.get('minProducts'), df.get('minDays')
        if not (isinstance(mp, int) and mp >= 1 and isinstance(md, int) and md >= 1):
            problems.append(f'{name}: definition lacks minProducts/minDays')
            continue
        ids = [s.get('id') for s in d.get('staples', [])]
        if len(ids) != len(set(ids)):
            problems.append(f'{name}: repeated staple id')
        for s in d.get('staples', []):
            rows = s.get('series') if name == OUT_WEEKLY else s.get('weeks')
            weeks = [r.get('week') for r in rows or []] + list(s.get('withheld', []))
            for w in weeks:
                if not isinstance(w, str) or not WEEK_RE.match(w):
                    problems.append(f'{name}: {s.get("id")}: bad week {w!r}')
            ws = [r.get('week') for r in rows or []]
            if ws != sorted(ws) or len(ws) != len(set(ws)):
                problems.append(f'{name}: {s.get("id")}: weeks not ascending and unique')
            if set(ws) & set(s.get('withheld', [])):
                problems.append(f'{name}: {s.get("id")}: a week is both published and withheld')
            for r in rows or []:
                if name == OUT_WEEKLY:
                    if set(r) != {'week', 'n', 'medianUnitPrice'}:
                        problems.append(f'{name}: {s.get("id")} {r.get("week")}: unexpected keys')
                    elif r['n'] < mp:
                        problems.append(f'{name}: {s.get("id")} {r["week"]}: n {r["n"]} is below the floor {mp}')
                    elif not isinstance(r['medianUnitPrice'], (int, float)) or r['medianUnitPrice'] <= 0 or round(r['medianUnitPrice'], 2) != r['medianUnitPrice']:
                        problems.append(f'{name}: {s.get("id")} {r["week"]}: bad price')
                else:
                    if set(r) != {'week', 'matched', 'rose', 'fell', 'unchanged'}:
                        problems.append(f'{name}: {s.get("id")} {r.get("week")}: unexpected keys')
                    elif r['matched'] < mp:
                        problems.append(f'{name}: {s.get("id")} {r["week"]}: matched {r["matched"]} is below the floor {mp}')
                    elif r['rose'] + r['fell'] + r['unchanged'] != r['matched']:
                        problems.append(f'{name}: {s.get("id")} {r["week"]}: rose+fell+unchanged is not matched')
    if len(docs) == 2:
        a = [(s['id'], s['name']) for s in docs[OUT_WEEKLY].get('staples', [])]
        b = [(s['id'], s['name']) for s in docs[OUT_MOVES].get('staples', [])]
        if a != b:
            problems.append('the two files do not list the same staples')
        if docs[OUT_WEEKLY].get('definition') != docs[OUT_MOVES].get('definition'):
            problems.append('the two files have different definitions')
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--basket')
    ap.add_argument('--staples')
    ap.add_argument('--min-products', type=int)
    ap.add_argument('--min-days', type=int)
    ap.add_argument('--out-dir', default='data')
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args(argv)
    if a.check:
        problems = check_files(a.out_dir)
        for p in problems:
            print('PROBLEM', p)
        if problems:
            return 1
        print('staple files are well formed')
        return 0
    missing = [n for n, v in (('--basket', a.basket), ('--staples', a.staples), ('--min-products', a.min_products), ('--min-days', a.min_days)) if v is None]
    if missing:
        ap.error('required: ' + ', '.join(missing))
    try:
        weekly, moves, skipped = build(a.basket, a.staples, a.min_products, a.min_days)
    except BuildError as e:
        print(f'stopped: {e}', file=sys.stderr)
        return 1
    write_atomic(os.path.join(a.out_dir, OUT_WEEKLY), dump(weekly))
    write_atomic(os.path.join(a.out_dir, OUT_MOVES), dump(moves))
    pub = sum(len(s['series']) for s in weekly['staples'])
    print(f'wrote {OUT_WEEKLY} ({len(weekly["staples"])} staples, {pub} staple-weeks) and {OUT_MOVES}; skipped rows: {dict(skipped) or "none"}')
    problems = check_files(a.out_dir)
    for p in problems:
        print('PROBLEM', p)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
