"""Tests for the authority-yield fetch and build. NO token and NO network: the credential reader and the HTTP opener
are fakes, and the real reader is refused inside a Claude Code session before it is reached. The fixtures follow the
review figures of 6 Nov 2026 (authority-yield-review-and-promote-6-nov.md): Leeds all 5.4%, Cardiff all 5.1%,
Kensington and Chelsea houses withheld for both reasons, Tower Hamlets detached with 3 sales.

    python -I -B docs/release/test_authority_yield.py
"""

from __future__ import annotations

import contextlib
import csv
import email.message
import io
import json
import os
import shutil
import ssl
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
import urllib.response
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import authority_yield_site as site  # noqa: E402
import fetch_authority_yield as fetch  # noqa: E402

REPO = HERE.parent.parent
TOKEN = 'FAKEtokenFORtests0123456789abcdef'   # not an apify_api_ prefix: no secret-scanning hit
BUILT = '2026-11-06T08:39:07.123456Z'
NOW = datetime(2026, 12, 31, 12, 0, tzinfo=UTC)     # the tests' clock: after every fixture's month and builtAt
TYPES = ('all', 'detached', 'semi-detached', 'terraced', 'flat')


# ------------------------------------------------------------------------------ fixtures (the Actor's rules, copied)

def actor_yield(rent, median):
    """authority_yield.gross_yield_pct at 3e9ee16."""
    if rent is None or median is None or median <= 0:
        return None
    return float((Decimal(rent) * 12 / Decimal(median) * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))


def actor_withhold(rows):
    """authority_yield.withhold_type_yields at 3e9ee16."""
    all_yield = next((r['grossYieldPct'] for r in rows if r['propertyType'] == 'all'), None)
    for r in rows:
        if r['propertyType'] == 'all' or r['grossYieldPct'] is None:
            continue
        if r['sales12m'] < 20:
            r['grossYieldPct'], r['yieldWithheld'] = None, site.WITHHELD_FEW_SALES
        elif all_yield is not None and Decimal(str(r['grossYieldPct'])) < Decimal(str(all_yield)) * Decimal('0.5'):
            r['grossYieldPct'], r['yieldWithheld'] = None, site.WITHHELD_NOT_ALIKE


# (code, name, {type: (rent, sales, median)}, bedroom rents on the all row)
AUTHORITIES = [
    ('E08000035', 'Leeds', {'all': (1125, 9800, 250000), 'detached': (1500, 1400, 420000), 'semi-detached': (1200, 3100, 265000),
                            'terraced': (1050, 3300, 205000), 'flat': (950, 2000, 160000)}, (850, 1050, 1300, 1700)),
    ('E09000020', 'Kensington and Chelsea', {'all': (4100, 1200, 1200000), 'detached': (2850, 15, 5600000),
                                             'semi-detached': (2862, 25, 4900000), 'terraced': (4000, 40, 2800000),
                                             'flat': (3300, 900, 800000)}, (2600, 3500, 5200, 8100)),
    ('E09000030', 'Tower Hamlets', {'all': (2400, 2600, 520000), 'detached': (2900, 3, None), 'semi-detached': (2500, 6, 700000),
                                    'terraced': (2700, 120, 690000), 'flat': (2300, 2400, 470000)}, (2000, 2500, 3100, 3900)),
    ('W06000015', 'Cardiff', {'all': (1150, 3500, 270000), 'detached': (1700, 400, 470000), 'semi-detached': (1300, 900, 300000),
                              'terraced': (1100, 1400, 235000), 'flat': (950, 800, 180000)}, (850, 1050, 1350, 1800)),
    ('W06000001', 'Ynys Môn', {'all': (820, 600, 220000), 'detached': (950, 280, 300000), 'semi-detached': (800, 120, 190000),
                               'terraced': (700, 150, 150000), 'flat': (650, 30, 120000)}, (600, 750, 900, 1200)),
    ('E07000999', 'Example District', {t: (900, 0, None) for t in TYPES}, (700, 850, 1000, None)),
]


def make_rows(month='2026-10', edition='2026-10-21', authorities=AUTHORITIES):
    rows = []
    for code, name, by_type, bedrooms in authorities:
        group = []
        for t in TYPES:
            rent, sales, median = by_type[t]
            row = {'month': month, 'periodFrom': site._month_minus(month, 14), 'periodTo': site._month_minus(month, 3), 'piprEdition': edition,
                   'authorityCode': code, 'authorityName': name, 'country': 'England' if code[0] == 'E' else 'Wales',
                   'propertyType': t, 'rentMonthly': rent, 'sales12m': sales, 'medianPrice12m': median,
                   'grossYieldPct': actor_yield(rent, median), 'yieldWithheld': None, 'lowSample': sales < 20}
            for column, value in zip(site.BEDROOM_COLUMNS, bedrooms):
                row[column] = value if t == 'all' else None
            group.append(row)
        actor_withhold(group)
        rows += group
    return rows


def yield_csv(rows):
    """authority_yield.yield_csv at 3e9ee16."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator='\n')
    writer.writerow(site.COLUMNS)
    for row in rows:
        writer.writerow(['' if row[c] is None else ('true' if row[c] is True else 'false' if row[c] is False else row[c])
                         for c in site.COLUMNS])
    return out.getvalue()


def attribution(year='2026'):
    return [f'Contains HM Land Registry data © Crown copyright and database right {year}. This data is licensed under the Open Government Licence v3.0.',
            'Source: Office for National Statistics licensed under the Open Government Licence v3.0.',
            f'Contains OS data © Crown copyright and database right {year}. Contains Royal Mail data © Royal Mail copyright and database right {year}.']


def make_files(month='2026-10', edition='2026-10-21', built=BUILT, rows=None):
    rows = make_rows(month, edition) if rows is None else rows
    document = {'v': 2, 'title': site.TITLE, 'month': month, 'periodFrom': site._month_minus(month, 14), 'periodTo': site._month_minus(month, 3), 'lagMonths': 3,
                'piprEdition': edition, 'builtAt': built, 'licence': site.LICENCE, 'attribution': attribution(built[:4]),
                'method': site.METHOD, 'columns': list(site.COLUMNS), 'rows': rows}
    state = {'v': 2, 'month': month, 'piprEdition': edition, 'builtAt': built, 'authorities': len(rows) // 5, 'rows': len(rows)}
    return {'AY_STATE': json.dumps(state).encode(),
            'yield_latest.json': json.dumps(document, ensure_ascii=False, separators=(',', ':')).encode('utf-8'),
            'yield_latest.csv': yield_csv(rows).encode('utf-8')}


FIXTURE_PINNED = {code: name for code, name, _, _ in AUTHORITIES}


class PinnedFixture:
    """The build's reviewed list pointed at a temporary file holding the fixture authorities (or `pairs`)."""

    def __init__(self, pairs=None):
        self.pairs = FIXTURE_PINNED if pairs is None else pairs

    def __enter__(self):
        self.dir = tempfile.TemporaryDirectory()
        path = Path(self.dir.name, 'pinned.json')
        path.write_text(json.dumps({'note': 'fixture', 'authorities': self.pairs}, ensure_ascii=False), encoding='utf-8')
        self.patch = mock.patch.object(site, 'PINNED_FILE', path)
        self.patch.start()
        return path

    def __exit__(self, *exc):
        self.patch.stop()
        self.dir.cleanup()


class SiteRoot:
    def __enter__(self) -> Path:
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        (root / 'rental-yield').mkdir()
        shutil.copy(REPO / 'rental-yield' / 'index.html', root / 'rental-yield' / 'index.html')
        shutil.copy(REPO / 'sitemap.xml', root / 'sitemap.xml')
        (root / 'CNAME').write_text('data.yappman.com\n', encoding='utf-8')
        return root

    def __exit__(self, *exc: object) -> None:
        self.dir.cleanup()


def put_incoming(root, files):
    folder = root / site.INCOMING
    folder.mkdir(parents=True, exist_ok=True)
    for key, body in files.items():
        (folder / fetch.SAVED_AS[key]).write_bytes(body)


def run_site(root, *argv, today='2026-11-06'):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = site.main(list(argv), root=root, today=today, now=NOW)
    return code, json.loads(out.getvalue())


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file() and '_incoming' not in p.parts}


def regenerated(files, change):
    """Edit the JSON rows, then write the CSV from them (so checks 1-3 pass and the row checks are what hold it)."""
    document = json.loads(files['yield_latest.json'])
    change(document)
    files = dict(files)
    files['yield_latest.json'] = json.dumps(document, ensure_ascii=False).encode('utf-8')
    files['yield_latest.csv'] = yield_csv(document['rows']).encode('utf-8')
    return files


# ------------------------------------------------------------------------------ the build

class BuildTests(unittest.TestCase):

    def setUp(self) -> None:
        # the fixtures hold 6 or 8 authorities; the real bound (300 to 330) is tested on its own below
        patcher = mock.patch.multiple(site, MIN_AUTHORITIES=1, MAX_AUTHORITIES=20)
        patcher.start()
        self.addCleanup(patcher.stop)
        pinned = PinnedFixture()
        pinned.__enter__()
        self.addCleanup(pinned.__exit__)

    def test_w_a_the_authority_count_bound(self) -> None:
        with mock.patch.multiple(site, MIN_AUTHORITIES=300, MAX_AUTHORITIES=330):
            self.assert_held(2, make_files())        # 6 authorities is far outside 300 to 330

    def test_w_a_a_published_authority_keeps_its_name(self) -> None:
        rows = make_rows(edition='2026-11-18')
        for r in rows:
            if r['authorityCode'] == 'E08000035':
                r['authorityName'] = 'John Smith'    # letters only, so only the live-name rule can hold it
        self.assert_held(7, make_files(edition='2026-11-18', built='2026-11-18T14:31:00Z', rows=rows), live_first=True)
        # W1: a new code (a reorganisation) is held until a person accepts it, then allowed, with a reminder
        more = make_rows(edition='2026-11-18', authorities=AUTHORITIES + [('E06000099', 'New Unitary', {t: (900, 0, None) for t in TYPES}, (1, 1, 1, 1))])
        with SiteRoot() as root:
            put_incoming(root, make_files())
            run_site(root, '--publish', '--first-publish')
            put_incoming(root, make_files(edition='2026-11-18', built='2026-11-18T14:31:00Z', rows=more))
            before = snapshot(root)
            code, result = run_site(root, '--publish')
            self.assertEqual((code, result['check']), (3, 7), result)
            self.assertIn('E06000099 New Unitary', result['reason'])
            self.assertEqual(snapshot(root), before)
            code, result = run_site(root, '--publish', '--accept-new-codes', 'E06000099')
            self.assertEqual(code, 0, result)
            self.assertEqual(result['acceptedNewCodes'], ['E06000099'])
            self.assertIn('rental-yield-authorities.json', result['reminder'])

    def test_w2_the_reviewed_list(self) -> None:
        # a code that is not on the list is held, and printed as a validated code/name pair
        with PinnedFixture({c: n for c, n in FIXTURE_PINNED.items() if c != 'E07000999'}):
            with SiteRoot() as root:
                put_incoming(root, make_files())
                before = snapshot(root)
                code, result = run_site(root, '--publish', '--first-publish')
                self.assertEqual((code, result['check']), (3, 7), result)
                self.assertIn('1 authority code(s)', result['reason'])
                self.assertIn('E07000999 Example District', result['reason'])
                self.assertEqual(snapshot(root), before)
                self.assertEqual(run_site(root, '--publish', '--first-publish', '--accept-new-codes', 'E07000999')[0], 0)
        # a name that differs from the list is held, with no override
        with PinnedFixture(FIXTURE_PINNED | {'E08000035': 'City of Leeds'}):
            self.assert_held(7, make_files())
        # a list that cannot be read, or holds a bad pair, holds every run
        with PinnedFixture(FIXTURE_PINNED | {'E08000099': 'Leeds 2'}):
            self.assert_held(7, make_files())
        with mock.patch.object(site, 'PINNED_FILE', Path(tempfile.gettempdir(), 'no-such-list.json')):
            self.assert_held(7, make_files())

    def test_w2_accept_new_codes_is_strict(self) -> None:
        with SiteRoot() as root:
            put_incoming(root, make_files())
            for value in ('E08000035', 'X1', 'E08000035;rm'):
                code, result = run_site(root, '--check', '--first-publish', '--accept-new-codes', value)
                self.assertEqual(code, 2, (value, result))

    def test_n9_counts_by_default_and_names_only_on_request(self) -> None:
        with SiteRoot() as root:
            put_incoming(root, make_files())
            code, result = run_site(root, '--check', '--first-publish')
            self.assertEqual((code, result['authorities']), (0, 6))
            self.assertNotIn('authorityList', result)
            self.assertNotIn('Leeds', json.dumps(result))
            code, result = run_site(root, '--check', '--first-publish', '--list-authorities')
            self.assertEqual(len(result['authorityList']), 6)
            self.assertIn('E08000035 Leeds', result['authorityList'])
            self.assertEqual(run_site(root, '--publish', '--first-publish', '--list-authorities')[0], 2)
            run_site(root, '--publish', '--first-publish')
            put_incoming(root, make_files(built='2026-11-05T00:00:00Z'))        # held against the live table
            code, result = run_site(root, '--publish')
            self.assertEqual(code, 3)
            self.assertNotIn('names', result['live'])

    def test_n8_a_live_builtat_that_is_not_a_real_time(self) -> None:
        with SiteRoot() as root:
            put_incoming(root, make_files())
            run_site(root, '--publish', '--first-publish')
            live = root / site.OUT / 'rental-yield-latest.json'
            document = json.loads(live.read_bytes())
            document['builtAt'] = '2026-11-31T25:61:61Z'
            live.write_bytes(json.dumps(document).encode())
            put_incoming(root, make_files(built='2026-11-07T08:00:00Z'))
            code, result = run_site(root, '--publish')
            self.assertEqual((code, result['check']), (3, 5), result)

    def test_w4_links_and_leftover_part_files_are_refused(self) -> None:
        for linked in ('_incoming', '_incoming/rental-yield', 'data/rental-yield', 'rental-yield/index.html', 'sitemap.xml'):
            with SiteRoot() as root:
                put_incoming(root, make_files())
                (root / 'data' / 'rental-yield').mkdir(parents=True)
                before = snapshot(root)
                target = root / linked
                with mock.patch.object(site, '_is_link', side_effect=lambda p, target=target: Path(p) == target):
                    code, result = run_site(root, '--publish', '--first-publish')
                self.assertEqual((code, result['code'], result['where']), (2, 'link-refused', str(Path(linked))), result)
                self.assertEqual(snapshot(root), before)
        with SiteRoot() as root:
            put_incoming(root, make_files())
            (root / 'data' / 'rental-yield').mkdir(parents=True)
            (root / 'data' / 'rental-yield' / 'rental-yield-latest.json.part').write_bytes(b'left over')
            before = snapshot(root)
            code, result = run_site(root, '--publish', '--first-publish')
            self.assertEqual((code, result['code']), (2, 'part-file-left-over'))
            self.assertEqual(snapshot(root), before)

    def test_the_committed_reviewed_list(self) -> None:
        pairs = site.load_pinned(HERE / 'rental-yield-authorities.json')
        self.assertEqual(len(pairs), 316)
        self.assertEqual(sum(c.startswith('E') for c in pairs), 294)
        self.assertEqual(sum(c.startswith('W') for c in pairs), 22)
        self.assertEqual(pairs['E08000035'], 'Leeds')

    def test_the_fixture_matches_the_review(self) -> None:
        rows = {(r['authorityName'], r['propertyType']): r for r in make_rows()}
        self.assertEqual(rows[('Leeds', 'all')]['grossYieldPct'], 5.4)
        self.assertEqual(rows[('Cardiff', 'all')]['grossYieldPct'], 5.1)
        self.assertEqual(rows[('Kensington and Chelsea', 'detached')]['yieldWithheld'], site.WITHHELD_FEW_SALES)
        self.assertEqual(rows[('Kensington and Chelsea', 'semi-detached')]['yieldWithheld'], site.WITHHELD_NOT_ALIKE)
        self.assertEqual(rows[('Kensington and Chelsea', 'terraced')]['yieldWithheld'], site.WITHHELD_NOT_ALIKE)
        self.assertIsNone(rows[('Tower Hamlets', 'detached')]['medianPrice12m'])
        self.assertIsNone(rows[('Tower Hamlets', 'detached')]['yieldWithheld'])
        self.assertEqual(rows[('Tower Hamlets', 'semi-detached')]['yieldWithheld'], site.WITHHELD_FEW_SALES)

    def test_first_publish_writes_files_page_and_lastmod(self) -> None:
        with SiteRoot() as root:
            files = make_files()
            put_incoming(root, files)
            code, result = run_site(root, '--publish', '--first-publish')
            self.assertEqual((code, result['status']), (0, 'published'), result)
            out = root / site.OUT
            self.assertEqual((out / 'rental-yield-latest.json').read_bytes(), files['yield_latest.json'])
            self.assertEqual((out / 'rental-yield-2026-10-pipr-2026-10-21.csv').read_bytes(), files['yield_latest.csv'])
            page = (root / site.PAGE).read_text(encoding='utf-8')
            for statement in attribution():
                self.assertIn(statement, page)
            self.assertIn(f'<p class="method">{site.html.escape(site.METHOD)}</p>', page)
            region = page.split('<!-- district-table:rows -->')[1].split('<!-- /district-table:rows -->')[0]
            self.assertEqual(region.count('<tr><td>'), 30)             # every row
            self.assertIn('<td>5.4%</td>', page)
            self.assertIn('&ndash;<sup><a href="#note-few">1</a></sup>', page)
            self.assertIn('&ndash;<sup><a href="#note-unlike">2</a></sup>', page)
            self.assertIn('Ynys Môn (W06000001)', page)
            self.assertNotIn('official', page.lower())
            self.assertIn('<loc>https://data.yappman.com/rental-yield/</loc>\n    <lastmod>2026-11-06</lastmod>',
                          (root / 'sitemap.xml').read_text(encoding='utf-8').replace('\r\n', '\n'))

    def test_same_build_again_is_nothing_new_and_check_writes_nothing(self) -> None:
        with SiteRoot() as root:
            put_incoming(root, make_files())
            before = snapshot(root)
            self.assertEqual(run_site(root, '--check', '--first-publish')[1]['status'], 'checks-passed')
            self.assertEqual(snapshot(root), before)
            run_site(root, '--publish', '--first-publish')
            before = snapshot(root)
            self.assertEqual(run_site(root, '--publish'), (0, {'status': 'nothing-new', 'month': '2026-10', 'piprEdition': '2026-10-21'}))
            self.assertEqual(snapshot(root), before)

    def test_first_publish_flag(self) -> None:
        with SiteRoot() as root:
            put_incoming(root, make_files())
            self.assertEqual(run_site(root, '--publish')[0], 2)
            run_site(root, '--publish', '--first-publish')
            put_incoming(root, make_files(built='2026-11-07T08:00:00Z'))
            self.assertEqual(run_site(root, '--publish', '--first-publish')[0], 2)

    def test_a_new_edition_is_archived_beside_the_old_and_old_ones_are_never_rewritten(self) -> None:
        with SiteRoot() as root:
            first = make_files()
            put_incoming(root, first)
            run_site(root, '--publish', '--first-publish')
            put_incoming(root, make_files(edition='2026-11-18', built='2026-11-18T14:31:00Z'))
            self.assertEqual(run_site(root, '--publish')[0], 0)
            out = root / site.OUT
            self.assertEqual((out / 'rental-yield-2026-10-pipr-2026-10-21.json').read_bytes(), first['yield_latest.json'])
            self.assertTrue((out / 'rental-yield-2026-10-pipr-2026-11-18.json').exists())
            page = (root / site.PAGE).read_text(encoding='utf-8')
            self.assertLess(page.index('pipr-2026-11-18.csv'), page.index('pipr-2026-10-21.csv'))
            # a later build of the same month and edition updates the latest files only
            second = make_files(edition='2026-11-18', built='2026-11-18T14:31:00Z')
            rows = make_rows(edition='2026-11-18')
            rows[0]['sales12m'] += 1
            rows[0]['lowSample'] = rows[0]['sales12m'] < 20
            third = make_files(edition='2026-11-18', built='2026-11-19T14:31:00Z', rows=rows)
            put_incoming(root, third)
            code, result = run_site(root, '--publish')
            self.assertEqual(code, 0, result)
            self.assertTrue(any(line.startswith('kept the rental-yield-2026-10-pipr-2026-11-18 archive') for line in result['done']))
            for ext, key in (('json', 'yield_latest.json'), ('csv', 'yield_latest.csv')):
                self.assertEqual((out / f'rental-yield-2026-10-pipr-2026-11-18.{ext}').read_bytes(), second[key])
                self.assertEqual((out / f'rental-yield-latest.{ext}').read_bytes(), third[key])

    def assert_held(self, check, files, live_first=False):
        with SiteRoot() as root:
            if live_first:
                put_incoming(root, make_files())
                run_site(root, '--publish', '--first-publish')
            put_incoming(root, files)
            before = snapshot(root)
            code, result = run_site(root, '--publish', *(() if live_first else ('--first-publish',)))
            self.assertEqual((code, result['status'], result.get('check')), (3, 'held', check), result)
            self.assertEqual(snapshot(root), before)

    def edited(self, key, change):
        files = make_files()
        name = 'AY_STATE' if key == 'state' else 'yield_latest.json'
        value = json.loads(files[name])
        change(value)
        files[name] = json.dumps(value, ensure_ascii=False).encode('utf-8')
        return files

    def test_check_1_versions_keys_and_columns(self) -> None:
        self.assert_held(1, self.edited('state', lambda s: s.update(v=1)))
        self.assert_held(1, self.edited('json', lambda d: d.update(v=2.0)))
        self.assert_held(1, self.edited('json', lambda d: d['columns'].reverse()))
        self.assert_held(1, self.edited('json', lambda d: d.update(note='<script>x</script>')))
        self.assert_held(1, self.edited('state', lambda s: s.update(extra=1)))
        files = make_files()
        files['yield_latest.json'] = files['yield_latest.json'].replace(b'"authorityName":"Leeds"', b'"authorityName":"Leeds 1AA","authorityName":"Leeds"', 1)
        self.assert_held(1, files)

    def test_check_2_one_build_and_pinned_fields(self) -> None:
        self.assert_held(2, self.edited('json', lambda d: d.update(builtAt='2026-11-06T09:00:00Z')))
        self.assert_held(2, self.edited('json', lambda d: d.update(piprEdition='2026-09-16')))
        self.assert_held(2, self.edited('state', lambda s: s.update(rows=29)))
        self.assert_held(2, self.edited('json', lambda d: d.update(method=d['method'] + ' Official figures.')))
        self.assert_held(2, self.edited('json', lambda d: d.update(title='Official rental yields')))
        self.assert_held(2, self.edited('json', lambda d: d.update(lagMonths=2)))
        self.assert_held(2, regenerated(make_files(), lambda d: [d.update(periodFrom='2025-07')] + [r.update(periodFrom='2025-07') for r in d['rows']]))
        self.assert_held(2, regenerated(make_files(), lambda d: [d.update(periodTo='2026-06')] + [r.update(periodTo='2026-06') for r in d['rows']]))
        self.assert_held(2, make_files('2027-01', built='2026-12-31T00:00:00Z'))         # a month after the clock
        self.assert_held(2, make_files(built='2026-12-31T14:00:00Z'))                   # built two hours ahead
        self.assert_held(2, make_files(built='2026-11-31T25:61:61Z'))                   # not a real time (re-review 2)

    def test_check_3_the_csv_matches(self) -> None:
        def csv_edit(change):
            files = make_files()
            files['yield_latest.csv'] = change(files['yield_latest.csv'].decode('utf-8')).encode('utf-8')
            return files
        self.assert_held(3, csv_edit(lambda t: t.replace(',250000,', ',250001,', 1)))
        self.assert_held(3, csv_edit(lambda t: t.replace(',250000,', ',2.5E5,', 1)))
        self.assert_held(3, csv_edit(lambda t: t.replace('month,', 'mnth,', 1)))
        self.assert_held(3, csv_edit(lambda t: t.rsplit('\n', 2)[0] + '\n'))

    def test_check_5_and_6_against_live(self) -> None:
        self.assert_held(5, make_files('2026-09', built='2026-11-07T08:00:00Z'), live_first=True)
        self.assert_held(5, make_files(edition='2026-09-16', built='2026-11-07T08:00:00Z'), live_first=True)
        self.assert_held(5, make_files(built='2026-11-06T08:39:07Z'), live_first=True)   # BUILT less its fraction
        bigger = make_rows(authorities=AUTHORITIES + [('E07000998', 'Other District', {t: (900, 0, None) for t in TYPES}, (1, 1, 1, 1)),
                                                      ('E07000997', 'Third District', {t: (900, 0, None) for t in TYPES}, (1, 1, 1, 1))])
        self.assert_held(6, make_files('2026-11', built='2026-12-05T14:31:00Z', rows=bigger), live_first=True)

    def test_check_7_the_rule_and_the_rows_are_enforced(self) -> None:
        rows = make_rows()
        index = {(r['authorityName'], r['propertyType']): i for i, r in enumerate(rows)}
        k_det, k_semi, leeds_all = index[('Kensington and Chelsea', 'detached')], index[('Kensington and Chelsea', 'semi-detached')], index[('Leeds', 'all')]

        def row(i, **fields):
            return lambda d: d['rows'][i].update(fields)
        for change in (
            row(k_det, grossYieldPct=0.6, yieldWithheld=None),          # a yield the rule withholds, shown
            row(k_semi, yieldWithheld=site.WITHHELD_FEW_SALES),        # the wrong reason
            row(k_det, yieldWithheld='withheld for no reason'),        # a reason that is not one of the two
            row(leeds_all, grossYieldPct=5.5),                          # a yield that is not rent x 12 / median
            row(leeds_all, yieldWithheld=site.WITHHELD_FEW_SALES),      # the all row is never withheld
            row(index[('Leeds', 'flat')], rentOneBed=850),              # a bedroom rent off the all row
            row(index[('Tower Hamlets', 'detached')], medianPrice12m=700000),   # a median under 5 sales
            row(leeds_all, lowSample=True),
            row(leeds_all, country='Wales'),
            row(leeds_all, authorityCode='S12000036'),
            row(leeds_all, rentMonthly=0),
            row(leeds_all, sales12m=-1),
            row(leeds_all, sales12m=1_000_001),
            row(leeds_all, periodFrom='2025-07'),
        ):
            self.assert_held(7, regenerated(make_files(), change))
        # a bad name on all five Leeds rows, so only the name pattern can hold it (re-review 1)
        leeds = [i for i, r in enumerate(rows) if r['authorityCode'] == 'E08000035']
        for bad in ('Leeds <b>', 'Leeds LS1 4AP', 'Leeds 2', 'Leeds\u00b2', 'Leeds_x'):
            files = regenerated(make_files(), lambda d, bad=bad: [d['rows'][i].update(authorityName=bad) for i in leeds])
            with SiteRoot() as root:
                put_incoming(root, files)
                code, result = run_site(root, '--publish', '--first-publish')
                self.assertEqual((code, result['check']), (3, 7), result)
                self.assertIn('the authority code or name', result['reason'])
        swapped = make_rows()
        swapped[0], swapped[1] = swapped[1], swapped[0]
        self.assert_held(7, make_files(rows=swapped))

    def test_check_8_attribution_word_for_word(self) -> None:
        def attr(change):
            return self.edited('json', lambda d: d.update(attribution=change(d['attribution'])))
        self.assert_held(8, attr(lambda a: a[:2]))
        self.assert_held(8, attr(lambda a: [a[0] + ' <script>', a[1], a[2]]))
        self.assert_held(8, attr(lambda a: [a[0].replace('2026', '2025'), a[1], a[2]]))
        self.assert_held(8, attr(lambda a: [a[1], a[0], a[2]]))

    def test_a_broken_template_and_a_half_archive_write_nothing(self) -> None:
        with SiteRoot() as root:
            page = root / site.PAGE
            page.write_text(page.read_text(encoding='utf-8').replace('<!-- /district-table:rows -->', ''), encoding='utf-8')
            put_incoming(root, make_files())
            before = snapshot(root)
            code, result = run_site(root, '--publish', '--first-publish')
            self.assertEqual((code, result['code']), (3, 'template-broken'))
            self.assertEqual(snapshot(root), before)
        with SiteRoot() as root:
            put_incoming(root, make_files())
            run_site(root, '--publish', '--first-publish')
            (root / site.OUT / 'rental-yield-2026-10-pipr-2026-10-21.json').unlink()
            put_incoming(root, make_files(edition='2026-11-18', built='2026-11-18T14:31:00Z'))
            before = snapshot(root)
            self.assertEqual(run_site(root, '--publish')[0], 2)
            self.assertEqual(snapshot(root), before)

    def test_a_hand_edited_live_file_is_held_and_outside_the_repo_is_refused(self) -> None:
        with SiteRoot() as root:
            put_incoming(root, make_files())
            run_site(root, '--publish', '--first-publish')
            (root / site.OUT / 'rental-yield-latest.json').write_bytes(b'{not json')
            put_incoming(root, make_files(built='2026-11-07T08:00:00Z'))
            code, result = run_site(root, '--publish')
            self.assertEqual((code, result['check']), (3, 5))
        with SiteRoot() as root:
            (root / 'CNAME').write_text('example.com', encoding='utf-8')
            put_incoming(root, make_files())
            self.assertEqual(run_site(root, '--check', '--first-publish')[0], 2)

    def test_the_district_table_files_are_not_touched(self) -> None:
        with SiteRoot() as root:
            put_incoming(root, make_files())
            run_site(root, '--publish', '--first-publish')
            self.assertFalse((root / 'data' / 'sold-prices').exists())
            self.assertFalse((root / 'sold-prices').exists())


# ------------------------------------------------------------------------------ the fetch

class FakeReply:
    def __init__(self, status, body):
        self.status, self._body = status, body

    def read(self, n):
        return self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


class FakeOpener:
    def __init__(self, files, script=None):
        self.files, self.script, self.seen = dict(files), script or {}, []

    def open(self, request, timeout):
        self.seen.append(request)
        n = len(self.seen)
        if n in self.script:
            status, body = self.script[n]
        else:
            key = request.full_url.rsplit('/', 1)[1]
            status, body = (200, self.files[key]) if key in self.files else (404, b'')
        if status >= 300:
            raise urllib.error.HTTPError(request.full_url, status, 'x', {}, io.BytesIO(b'body-with-detail'))
        return FakeReply(status, body)


class FakeHTTPS(urllib.request.BaseHandler):
    """An https_open that answers without a socket, so the REAL opener (proxy, redirect and error handlers) runs."""

    def __init__(self, status, body=b'', headers=None):
        self.status, self.body, self.headers, self.seen = status, body, headers or {}, []

    def https_open(self, request):
        self.seen.append(request)
        message = email.message.Message()
        for key, value in self.headers.items():
            message[key] = value
        reply = urllib.response.addinfourl(io.BytesIO(self.body), message, request.full_url, self.status)
        reply.msg = 'x'
        return reply


class FetchRoot:
    def __enter__(self):
        self.dir = tempfile.TemporaryDirectory()
        Path(self.dir.name, 'CNAME').write_text('data.yappman.com\n', encoding='utf-8')
        return self.dir.name

    def __exit__(self, *exc):
        self.dir.cleanup()


def run_fetch(root, opener, *argv, reader=lambda: TOKEN):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = fetch.main(list(argv), reader=reader, opener=opener, root=Path(root), sleep=lambda s: None)
    return code, out.getvalue()


class FetchTests(unittest.TestCase):

    def test_refused_inside_claude_code_without_reaching_the_credential(self) -> None:
        with mock.patch.dict(os.environ, {'CLAUDECODE': '1'}), \
                mock.patch.object(fetch, '_credential_api', side_effect=AssertionError('reached')):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(fetch.main(['--dry-run']), 2)
            self.assertIn('refused-inside-claude-code', out.getvalue())
            with self.assertRaises(fetch.FetchError) as caught:
                fetch.read_token()
            self.assertEqual((caught.exception.code, caught.exception.exit_code), ('refused-inside-claude-code', 2))
            with self.assertRaises(fetch.FetchError) as caught:
                fetch.credential_token()
            self.assertEqual(caught.exception.code, 'refused-inside-claude-code')
        with mock.patch.dict(os.environ, {'CLAUDECODE': '1'}), FetchRoot() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(fetch.main(['--dry-run'], reader=lambda: TOKEN, root=Path(tmp)), 2)

    def test_w4_links_and_leftover_part_files_save_nothing(self) -> None:
        for linked in ('_incoming', '_incoming/rental-yield', '_incoming/rental-yield/yield_latest.json'):
            with FetchRoot() as tmp:
                target = Path(tmp) / linked
                with mock.patch.object(fetch, '_is_link', side_effect=lambda p, target=target: Path(p) == target):
                    code, out = run_fetch(tmp, FakeOpener(make_files()), '--fetch')
                self.assertEqual((code, json.loads(out)['code']), (2, 'link-refused'), linked)
                self.assertFalse(any((Path(tmp) / fetch.INCOMING).glob('*.json')))
        with FetchRoot() as tmp:
            folder = Path(tmp) / fetch.INCOMING
            folder.mkdir(parents=True)
            (folder / 'yield_latest.csv.part').write_bytes(b'left over')
            code, out = run_fetch(tmp, FakeOpener(make_files()), '--fetch')
            self.assertEqual((code, json.loads(out)['code']), (3, 'part-file-left-over'))
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ['yield_latest.csv.part'])

    def test_n2_a_malformed_builtat_or_edition_is_not_printed(self) -> None:
        for field, bad in (('builtAt', '2026-11-06 <script>'), ('builtAt', 'x' * 30), ('piprEdition', '2026-13-45')):
            state = json.loads(make_files()['AY_STATE'])
            state[field] = bad
            with FetchRoot() as tmp:
                code, out = run_fetch(tmp, FakeOpener({'AY_STATE': json.dumps(state).encode()}), '--dry-run')
            self.assertEqual((code, json.loads(out)['code']), (3, 'state-incomplete'), (field, bad))
            self.assertNotIn(bad, out)

    def test_refused_when_a_certificate_override_is_set(self) -> None:
        for name in fetch.TLS_OVERRIDES:
            with mock.patch.dict(os.environ, {name: 'C:/somewhere/ca.pem'}), FetchRoot() as tmp, \
                    mock.patch.object(fetch, '_credential_api', side_effect=AssertionError('reached')), \
                    mock.patch.object(sys, 'flags', mock.Mock(isolated=1)):
                os.environ.pop('CLAUDECODE', None)
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(fetch.main(['--dry-run'], opener=FakeOpener(make_files()), root=Path(tmp)), 2)
                self.assertIn('tls-override-set', out.getvalue())
        self.assertEqual(set(fetch.TLS_OVERRIDES), {'SSL_CERT_FILE', 'SSL_CERT_DIR', 'OPENSSL_CONF', 'OPENSSL_MODULES', 'OPENSSL_ENGINES'})

    def test_refused_without_python_I_and_outside_the_repo(self) -> None:
        with mock.patch.dict(os.environ, {}), FetchRoot() as tmp, \
                mock.patch.object(fetch, '_credential_api', side_effect=AssertionError('reached')), \
                mock.patch.object(sys, 'flags', mock.Mock(isolated=0)):
            os.environ.pop('CLAUDECODE', None)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(fetch.main(['--dry-run'], opener=FakeOpener(make_files()), root=Path(tmp)), 2)
            self.assertIn('run-with-python-I', out.getvalue())
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run_fetch(tmp, FakeOpener(make_files()), '--fetch')
            self.assertEqual((code, json.loads(out)['code']), (2, 'not-the-data-yappman-repo'))

    def test_dry_run_reads_ay_state_only(self) -> None:
        with FetchRoot() as tmp:
            opener = FakeOpener(make_files())
            code, out = run_fetch(tmp, opener, '--dry-run')
            self.assertEqual(code, 0, out)
            self.assertEqual([r.full_url.rsplit('/', 1)[1] for r in opener.seen], ['AY_STATE'])
            result = json.loads(out)
            self.assertEqual((result['state']['month'], result['state']['piprEdition'], result['state']['rows']), ('2026-10', '2026-10-21', 30))
            self.assertFalse((Path(tmp) / fetch.INCOMING).exists())

    def test_fetch_reads_the_three_keys_then_ay_state_again_and_saves(self) -> None:
        with FetchRoot() as tmp:
            files = make_files()
            opener = FakeOpener(files)
            code, out = run_fetch(tmp, opener, '--fetch')
            self.assertEqual(code, 0, out)
            self.assertEqual([r.full_url.rsplit('/', 1)[1] for r in opener.seen], ['AY_STATE', 'yield_latest.json', 'yield_latest.csv', 'AY_STATE'])
            for key, body in files.items():
                self.assertEqual((Path(tmp) / fetch.INCOMING / fetch.SAVED_AS[key]).read_bytes(), body)
            for request in opener.seen:
                self.assertEqual(request.get_method(), 'GET')
                self.assertEqual(request.get_header('Authorization'), 'Bearer ' + TOKEN)
                self.assertNotIn(TOKEN, request.full_url)
                self.assertFalse(any(c in request.full_url for c in '?#%'))
            for hidden in (TOKEN, 'pp-district-table', 'key-value-stores'):
                self.assertNotIn(hidden, out)

    def test_only_the_three_yield_keys_can_be_requested(self) -> None:
        for key in ('DT_STATE', 'table_latest.json', 'table_latest.csv', 'PP_STATE', 'yield_2026-10.json', '../records', 'AY_STATE?x=1', ''):
            with self.assertRaises(fetch.FetchError):
                fetch.record_url(key)

    def test_ay_state_changed_or_missing_saves_nothing(self) -> None:
        with FetchRoot() as tmp:
            later = make_files(built='2026-11-06T09:00:00Z')['AY_STATE']
            code, out = run_fetch(tmp, FakeOpener(make_files(), script={4: (200, later)}), '--fetch')
            self.assertEqual(code, 3)
            self.assertIn('state-changed-during-fetch', out)
            self.assertFalse((Path(tmp) / fetch.INCOMING).exists())
            self.assertEqual(run_fetch(tmp, FakeOpener({}), '--dry-run')[0], 3)
            old = {'AY_STATE': json.dumps({'v': 1, 'month': '2026-10'}).encode()}
            self.assertEqual(run_fetch(tmp, FakeOpener(old), '--dry-run')[0], 3)

    def test_the_real_opener_https_only_no_redirect_and_tls(self) -> None:
        opener = fetch.build_opener(FakeHTTPS(200))
        self.assertEqual(set(opener.handle_open), {'https'})
        context = fetch.tls_context()
        self.assertIsNone(context.keylog_filename)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        handler = FakeHTTPS(302, headers={'Location': 'https://elsewhere.example/steal'})
        with FetchRoot() as tmp:
            code, out = run_fetch(tmp, fetch.build_opener(handler), '--dry-run')
        self.assertEqual((code, json.loads(out)['code']), (4, 'redirect-refused'))
        self.assertEqual(len(handler.seen), 1)
        with FetchRoot() as tmp:
            code, out = run_fetch(tmp, fetch.build_opener(FakeHTTPS(200, make_files()['AY_STATE'])), '--dry-run')
        self.assertEqual(code, 0, out)

    def test_errors_print_codes_only(self) -> None:
        class Leaky:
            def open(self, request, timeout):
                raise OSError('failed for ' + request.full_url + ' with ' + request.get_header('Authorization'))
        with FetchRoot() as tmp:
            code, out = run_fetch(tmp, Leaky(), '--dry-run')
            self.assertEqual((code, json.loads(out)['code']), (4, 'network-failure'))
            self.assertNotIn(TOKEN, out)
            opener = FakeOpener(make_files(), script={1: (401, b'')})
            code, out = run_fetch(tmp, opener, '--dry-run')
            self.assertEqual((code, len(opener.seen), json.loads(out)['httpStatus']), (4, 1, 401))
            opener = FakeOpener(make_files(), script={1: (503, b''), 2: (503, b''), 3: (503, b'')})
            self.assertEqual(run_fetch(tmp, opener, '--dry-run')[0], 4)
            self.assertEqual(len(opener.seen), 3)
        with FetchRoot() as tmp, mock.patch.object(fetch, 'MAX_RESPONSE_BYTES', 10):
            code, out = run_fetch(tmp, FakeOpener(make_files()), '--dry-run')
            self.assertEqual(json.loads(out)['code'], 'response-too-large')
        secret = fetch.Secret(TOKEN)
        self.assertEqual((repr(secret), str(secret), f'{secret}'), ('<secret>',) * 3)
        for bad in ('has space inside', 'short', 'line\nbreak0000'):
            with self.assertRaises(fetch.FetchError):
                fetch.Secret(bad)

    def test_fetch_then_build_end_to_end(self) -> None:
        with SiteRoot() as root, mock.patch.multiple(site, MIN_AUTHORITIES=1, MAX_AUTHORITIES=20), PinnedFixture():
            self.assertEqual(run_fetch(root, FakeOpener(make_files()), '--fetch')[0], 0)
            self.assertEqual(run_site(root, '--publish', '--first-publish')[0], 0)


if __name__ == '__main__':
    unittest.main(verbosity=1)
