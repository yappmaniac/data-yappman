"""A SYNTHETIC area history in the Actor's own format (price_paid/src/area_history.py, AREA_VERSION 1), for the builder's tests and for
trying the page. Invented names, codes and prices: it is NOT data and must never be published.

    python -I -B docs/release/area_history_fixture.py [FOLDER]      # default _incoming/synthetic-area-history

writes AH_STATE.json, ah_index.json and, for each of the 31 files the index lists, <key>.json and <key>.csv. Real fetched files go to
_incoming/sold-prices-area-history/ with the same names (see area_history_site.py).
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import area_history_site as ah  # noqa: E402

BUILT = '2026-11-20T10:53:22.123456Z'
RELEASE = 'AUG_2026'
LOOKUP_SHA = 'ef8470fe63a77945d17e730b546c25c62c296e256bffdc8ec76aae6264613ae2'
REGION_NAMES = {
    'E12000001': 'North East', 'E12000002': 'North West', 'E12000003': 'Yorkshire and The Humber', 'E12000004': 'East Midlands',
    'E12000005': 'West Midlands', 'E12000006': 'East of England', 'E12000007': 'London', 'E12000008': 'South East', 'E12000009': 'South West',
    'W92000004': 'Wales',
}
NAMES = ["Alpha Borough", "Beta, City of", "King’s Lynn and West Norfolk", "St. Helens"]
# (periodType, period, split, sales): sparse on purpose; rows with no sales are left out
YEAR_ROWS = [('year', '1995', 'all', 3), ('year', '1995', 'flat', 5), ('year', '2013', 'all', 18), ('year', '2014', 'all', 40), ('year', '2014', 'new-build', 12),
             ('year', '2025', 'all', 120), ('year', '2025', 'freehold', 60), ('year', '2025', 'existing', 100)]
QUARTER_ROWS = [('quarter', '1995-Q1', 'all', 2), ('quarter', '2009-Q4', 'detached', 7), ('quarter', '2010-Q1', 'all', 25), ('quarter', '2026-Q2', 'all', 30),
                ('quarter', '2026-Q2', 'flat', 5)]


def make(last_year: int = 2025, last_quarter: str = '2026-Q2', month: str = '2026-10', built: str = BUILT, unassigned: int = 786) -> dict[str, bytes]:
    year = int(built[:4])
    attribution = ah._expected_attribution(str(year))

    def row(ptype, period, geography, code, name, split, sales, scale):
        figs = (None, None, None) if sales < 5 else (200000 * scale + sales, 150000 * scale + sales, 260000 * scale + sales)
        return {'periodType': ptype, 'period': period, 'geography': geography, 'code': code, 'name': name, 'split': split, 'sales': sales,
                'median': figs[0], 'lowerQuartile': figs[1], 'upperQuartile': figs[2], 'lowSample': sales < 20}

    def doc(area, kind, block, rows):
        return {'v': 1, 'title': ah.TITLE, 'area': area, 'kind': kind, 'block': block, 'firstYear': 1995, 'lastYear': last_year, 'lastQuarter': last_quarter,
                'month': month, 'postcodeRelease': RELEASE, 'builtAt': built, 'licence': ah.LICENCE, 'attribution': attribution, 'method': ah.METHOD,
                'columns': list(ah.COLUMNS), 'rows': rows}

    def csv_text(rows):
        out = io.StringIO()
        w = csv.writer(out, lineterminator='\n')
        w.writerow(ah.COLUMNS)
        for r in rows:
            w.writerow(['' if r[c] is None else ('true' if r[c] is True else 'false' if r[c] is False else r[c]) for c in ah.COLUMNS])
        return out.getvalue()

    files: dict[str, bytes] = {}
    entries = []
    region_rows_all: list[dict] = []
    suppressed = 0
    n_authorities = 0
    for number, region in enumerate(sorted(REGION_NAMES), start=1):
        prefix = 'W06' if region.startswith('W') else 'E06'
        auths = [(f'{prefix}{number * 100 + i:06d}', NAMES[(number + i) % len(NAMES)]) for i in range(2 if number % 3 else 3)]
        n_authorities += len(auths)
        auth_rows: dict[str, list] = {'year': [], 'q0': [], 'q1': []}
        sums: dict[tuple, int] = {}
        for k, (code, name) in enumerate(auths):
            for ptype, period, split, sales in YEAR_ROWS + QUARTER_ROWS:
                s = sales + k * 4
                r = row(ptype, period, 'authority', code, name, split, s, number)
                suppressed += s < 5
                if ptype == 'year':
                    auth_rows['year'].append(r)
                else:
                    auth_rows['q0' if int(period[:4]) <= 2009 else 'q1'].append(r)
                sums[(ptype, period, split)] = sums.get((ptype, period, split), 0) + s
        for (ptype, period, split), s in sums.items():
            region_rows_all.append(row(ptype, period, 'region', region, REGION_NAMES[region], split, s, number))
            suppressed += s < 5
        for key, kind, block, rows in ((f'ah_{region}_year', 'authority-year', None, auth_rows['year']),
                                       (f'ah_{region}_qtr_1995-2009', 'authority-quarter', '1995-2009', auth_rows['q0']),
                                       (f'ah_{region}_qtr_2010-onwards', 'authority-quarter', '2010-onwards', auth_rows['q1'])):
            files[key + '.json'] = json.dumps(doc(region, kind, block, rows), ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            files[key + '.csv'] = csv_text(rows).encode('utf-8')
            entries.append({'key': key, 'region': region, 'regionName': REGION_NAMES[region], 'kind': kind, 'block': block, 'rows': len(rows),
                            'authorities': len(auths)})
    region_rows_all.sort(key=lambda r: (r['periodType'] != 'year', r['code'], r['period']))
    files['ah_regions.json'] = json.dumps(doc(None, 'region', None, region_rows_all), ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    files['ah_regions.csv'] = csv_text(region_rows_all).encode('utf-8')
    entries.append({'key': 'ah_regions', 'region': None, 'regionName': None, 'kind': 'region', 'block': None, 'rows': len(region_rows_all),
                    'authorities': n_authorities})
    total_rows = sum(e['rows'] for e in entries)
    index = {'v': 1, 'title': ah.TITLE, 'firstYear': 1995, 'lastYear': last_year, 'lastQuarter': last_quarter, 'month': month, 'postcodeRelease': RELEASE,
             'builtAt': built, 'licence': ah.LICENCE, 'attribution': attribution, 'method': ah.METHOD, 'columns': list(ah.COLUMNS), 'files': entries,
             'totals': {'authorities': n_authorities, 'regions': 10, 'files': len(entries), 'rows': total_rows, 'suppressed': suppressed,
                        'unassignedSales': unassigned}}
    state = {'v': 1, 'month': month, 'lastYear': last_year, 'lastQuarter': last_quarter, 'postcodeRelease': RELEASE, 'regionLookupSha256': LOOKUP_SHA,
             'builtAt': built, 'authorities': n_authorities, 'regions': 10, 'files': len(entries), 'rows': total_rows}
    files['ah_index.json'] = json.dumps(index, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    files['AH_STATE.json'] = json.dumps(state, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return files


def write(folder: Path, **kwargs) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    files = make(**kwargs)
    for name, data in files.items():
        (folder / name).write_bytes(data)
    return len(files)


if __name__ == '__main__':
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ah.REPO / '_incoming' / 'synthetic-area-history'
    print(f'wrote {write(target)} synthetic files to {target}')
