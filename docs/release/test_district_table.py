"""Tests for the district-table fetch and build. NO token and NO network: the credential reader and the HTTP opener
are fakes, and the real reader is refused inside a Claude Code session before it is reached.

    python -I -B docs/release/test_district_table.py
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
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import district_table_site as site  # noqa: E402
import fetch_district_table as fetch  # noqa: E402

REPO = HERE.parent.parent
TOKEN = 'FAKEtokenFORtests0123456789abcdef'   # not an apify_api_ prefix: no secret-scanning hit
BUILT = '2026-11-05T12:01:15.123456Z'


# ------------------------------------------------------------------------------ fixtures (the Actor's file format)

def make_rows(month: str = '2026-10', districts: tuple[str, ...] = ('LS6', 'M1', 'SW11')) -> list[dict]:
    rows = []
    for n, district in enumerate(districts):
        for kind, base in (('all', 250_000), ('detached', 410_000), ('flat', 180_000)):
            sales = 40 + 7 * n if kind == 'all' else 4 + n
            shown = sales >= 5
            median = base + 1_000 * n if shown else None
            previous = int((base + 1_000 * n) / 1.03) if sales + 2 >= 5 else None
            rows.append({
                'month': month, 'periodFrom': '2025-08', 'periodTo': '2026-07', 'district': district,
                'localAuthorityCodes': 'E08000035' if district == 'LS6' else 'E08000003;E08000035',
                'propertyType': kind, 'sales12m': sales, 'median12m': median,
                'lowerQuartile12m': median - 20_000 if shown else None,
                'upperQuartile12m': median + 30_000 if shown else None,
                'sales3m': sales // 4, 'median3m': median if sales // 4 >= 5 else None,
                'salesPrev12m': sales + 2, 'medianPrev12m': previous,
                'medianChangePct': 3.0 if shown and previous is not None else None, 'lowSample': sales < 20,
            })
    return rows


def table_csv(rows: list[dict]) -> str:
    """The Actor's table_csv (price_paid/src/district_table.py), line for line."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator='\n')
    writer.writerow(site.COLUMNS)
    for row in rows:
        writer.writerow(['' if row[c] is None else ('true' if row[c] is True else 'false' if row[c] is False else row[c])
                         for c in site.COLUMNS])
    return out.getvalue()


def make_files(month: str = '2026-10', built: str = BUILT, rows: list[dict] | None = None) -> dict[str, bytes]:
    rows = make_rows(month) if rows is None else rows
    document = {
        'v': 2, 'title': site.TITLE, 'month': month, 'periodFrom': '2025-08', 'periodTo': '2026-07',
        'previousPeriodFrom': '2024-08', 'previousPeriodTo': '2025-07', 'threeMonthFrom': '2026-05', 'lagMonths': 3,
        'postcodeRelease': 'AUG_2026', 'builtAt': built, 'licence': site.LICENCE,
        'attribution': [
            'Contains HM Land Registry data © Crown copyright and database right 2026. This data is licensed under the Open Government Licence v3.0.',
            'Local authority codes: Source: Office for National Statistics licensed under the Open Government Licence v3.0. Contains OS data © Crown copyright and database right 2026. Contains Royal Mail data © Royal Mail copyright and database right 2026.',
        ],
        'method': site.METHOD, 'columns': list(site.COLUMNS), 'rows': rows,
    }
    state = {'v': 2, 'month': month, 'postcodeRelease': 'AUG_2026', 'builtAt': built, 'districts': 3, 'rows': len(rows)}
    return {
        'DT_STATE': json.dumps(state).encode(),
        'table_latest.json': json.dumps(document, ensure_ascii=False, separators=(',', ':')).encode('utf-8'),
        'table_latest.csv': table_csv(rows).encode('utf-8'),
    }


class SiteRoot:
    """A temporary copy of the parts of the repo the build touches."""

    def __enter__(self) -> Path:
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        (root / 'sold-prices').mkdir()
        (root / 'CNAME').write_text('data.yappman.com\n', encoding='utf-8')
        shutil.copy(REPO / 'sold-prices' / 'index.html', root / 'sold-prices' / 'index.html')
        shutil.copy(REPO / 'sitemap.xml', root / 'sitemap.xml')
        return root

    def __exit__(self, *exc: object) -> None:
        self.dir.cleanup()


def put_incoming(root: Path, files: dict[str, bytes]) -> None:
    folder = root / site.INCOMING
    folder.mkdir(parents=True, exist_ok=True)
    for key, body in files.items():
        (folder / fetch.SAVED_AS[key]).write_bytes(body)


def run_site(root: Path, *argv: str, today: str = '2026-11-06') -> tuple[int, dict]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = site.main(list(argv), root=root, today=today)
    return code, json.loads(out.getvalue())


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file() and '_incoming' not in p.parts}


# ------------------------------------------------------------------------------ the build

class BuildTests(unittest.TestCase):

    def test_first_publish_writes_files_page_and_lastmod(self) -> None:
        with SiteRoot() as root:
            files = make_files()
            put_incoming(root, files)
            code, result = run_site(root, '--publish', '--first-publish')
            self.assertEqual((code, result['status']), (0, 'published'))
            out = root / site.OUT
            for name in ('district-medians-latest.csv', 'district-medians-latest.json',
                         'district-medians-2026-10.csv', 'district-medians-2026-10.json'):
                self.assertTrue((out / name).exists(), name)
            self.assertEqual((out / 'district-medians-latest.json').read_bytes(), files['table_latest.json'])
            self.assertEqual((out / 'district-medians-2026-10.csv').read_bytes(), files['table_latest.csv'])
            page = (root / site.PAGE).read_text(encoding='utf-8')
            for statement in json.loads(files['table_latest.json'])['attribution']:
                self.assertIn(statement, page)
            self.assertIn('/data/sold-prices/district-medians-latest.csv', page)
            self.assertIn('/data/sold-prices/district-medians-2026-10.json', page)
            self.assertNotIn('No table has been published yet.', page)
            self.assertIn('<loc>https://data.yappman.com/sold-prices/</loc>\n    <lastmod>2026-11-06</lastmod>',
                          (root / 'sitemap.xml').read_text(encoding='utf-8').replace('\r\n', '\n'))

    def test_same_build_again_is_nothing_new(self) -> None:
        with SiteRoot() as root:
            put_incoming(root, make_files())
            run_site(root, '--publish', '--first-publish')
            before = snapshot(root)
            code, result = run_site(root, '--publish')
            self.assertEqual((code, result['status']), (0, 'nothing-new'))
            self.assertEqual(snapshot(root), before)

    def test_check_mode_writes_nothing(self) -> None:
        with SiteRoot() as root:
            put_incoming(root, make_files())
            before = snapshot(root)
            code, result = run_site(root, '--check', '--first-publish')
            self.assertEqual((code, result['status']), (0, 'checks-passed'))
            self.assertEqual(snapshot(root), before)

    def test_first_publish_flag_is_needed_and_refused_once_live(self) -> None:
        with SiteRoot() as root:
            put_incoming(root, make_files())
            before = snapshot(root)
            self.assertEqual(run_site(root, '--publish')[0], 2)
            self.assertEqual(snapshot(root), before)
            run_site(root, '--publish', '--first-publish')
            put_incoming(root, make_files(built='2026-11-06T12:00:00Z'))
            self.assertEqual(run_site(root, '--publish', '--first-publish')[0], 2)

    def test_missing_incoming_files_is_refused(self) -> None:
        with SiteRoot() as root:
            self.assertEqual(run_site(root, '--check')[0], 2)

    def test_a_dated_file_is_never_rewritten(self) -> None:
        with SiteRoot() as root:
            first = make_files()
            put_incoming(root, first)
            run_site(root, '--publish', '--first-publish')
            rows = make_rows()
            rows[0]['sales12m'] += 1
            again = make_files(built='2026-11-07T12:00:00Z', rows=rows)
            put_incoming(root, again)
            code, result = run_site(root, '--publish')
            self.assertEqual(code, 0)
            out = root / site.OUT
            self.assertEqual((out / 'district-medians-2026-10.json').read_bytes(), first['table_latest.json'])
            self.assertEqual((out / 'district-medians-2026-10.csv').read_bytes(), first['table_latest.csv'])
            self.assertEqual((out / 'district-medians-latest.json').read_bytes(), again['table_latest.json'])
            self.assertTrue(any(line.startswith('kept the 2026-10 archive') for line in result['done']))

    def test_a_new_month_is_archived_beside_the_old(self) -> None:
        with SiteRoot() as root:
            put_incoming(root, make_files())
            run_site(root, '--publish', '--first-publish')
            put_incoming(root, make_files('2026-11', '2026-12-05T12:00:00Z'))
            self.assertEqual(run_site(root, '--publish')[0], 0)
            page = (root / site.PAGE).read_text(encoding='utf-8')
            self.assertIn('district-medians-2026-11.csv', page)
            self.assertIn('district-medians-2026-10.csv', page)
            self.assertLess(page.index('district-medians-2026-11.csv'), page.index('district-medians-2026-10.csv'))

    def test_a_number_the_store_re_serialised_still_matches(self) -> None:
        files = make_files()
        document = json.loads(files['table_latest.json'])
        document['rows'][0]['medianChangePct'] = 3        # 3.0 written back as 3; the CSV keeps 3.0
        table = site.check_table(files['DT_STATE'], json.dumps(document).encode(), files['table_latest.csv'], None, True)
        self.assertEqual(table.rows, 9)

    def assert_held(self, check: int, files: dict[str, bytes], live_first: bool = False) -> None:
        with SiteRoot() as root:
            if live_first:
                put_incoming(root, make_files())
                run_site(root, '--publish', '--first-publish')
            put_incoming(root, files)
            before = snapshot(root)
            code, result = run_site(root, '--publish', *(() if live_first else ('--first-publish',)))
            self.assertEqual((code, result['status'], result['check']), (3, 'held', check), result)
            self.assertEqual(snapshot(root), before)

    def edited(self, key: str, change) -> dict[str, bytes]:
        files = make_files()
        if key == 'csv':
            files['table_latest.csv'] = change(files['table_latest.csv'].decode()).encode()
            return files
        name = 'DT_STATE' if key == 'state' else 'table_latest.json'
        value = json.loads(files[name])
        change(value)
        files[name] = json.dumps(value).encode()
        return files

    def test_check_1_versions_and_columns(self) -> None:
        self.assert_held(1, self.edited('state', lambda s: s.update(v=1)))
        self.assert_held(1, self.edited('json', lambda d: d.update(v=1)))
        self.assert_held(1, self.edited('json', lambda d: d.update(v=2.0)))
        self.assert_held(1, self.edited('json', lambda d: d['columns'].reverse()))

    def test_check_2_one_build(self) -> None:
        self.assert_held(2, self.edited('json', lambda d: d.update(builtAt='2026-11-05T13:00:00Z')))
        self.assert_held(2, self.edited('json', lambda d: d.update(month='2026-09')))
        self.assert_held(2, self.edited('state', lambda s: s.update(rows=8)))

    def test_check_3_the_csv_matches_cell_for_cell(self) -> None:
        self.assert_held(3, self.edited('csv', lambda t: t.replace('250000', '250001', 1)))
        self.assert_held(3, self.edited('csv', lambda t: t.replace('2026-10,', '2026-09,', 1)))
        self.assert_held(3, self.edited('csv', lambda t: t.replace('month,', 'mnth,', 1)))
        self.assert_held(3, self.edited('csv', lambda t: t.rsplit('\n', 2)[0] + '\n'))

    def test_check_5_not_older_than_live(self) -> None:
        self.assert_held(5, make_files('2026-09', '2026-11-06T12:00:00Z'), live_first=True)

    def test_check_6_row_count_within_20_percent(self) -> None:
        bigger = make_rows('2026-11', districts=('LS6', 'M1', 'SW11', 'B1'))
        self.assert_held(6, make_files('2026-11', '2026-12-05T12:00:00Z', rows=bigger), live_first=True)

    def test_check_7_cell_kinds_and_no_postcode(self) -> None:
        def row0(**fields):
            return lambda d: d['rows'][0].update(fields)
        for change in (row0(median12m='250000'), row0(sales12m=None), row0(lowSample='true'),
                       row0(district='LS6 1AA'), row0(district='LS6 1'), row0(localAuthorityCodes='S12000036'),
                       row0(propertyType='other')):
            files = self.edited('json', change)
            # the CSV is written from the edited rows, so checks 1 to 3 pass and check 7 is the one that holds it
            files['table_latest.csv'] = table_csv(json.loads(files['table_latest.json'])['rows']).encode()
            self.assert_held(7, files)

    def test_check_8_attribution(self) -> None:
        self.assert_held(8, self.edited('json', lambda d: d.update(attribution=[])))
        self.assert_held(8, self.edited('json', lambda d: d.update(attribution=['Contains HM Land Registry data', 'other'])))

    def test_c3_a_repeated_key_is_refused(self) -> None:
        files = make_files()
        raw = files['table_latest.json'].decode('utf-8')
        files['table_latest.json'] = raw.replace('"district":"LS6"', '"district":"LS6 1AA","district":"LS6"', 1).encode('utf-8')
        self.assertIn(b'LS6 1AA', files['table_latest.json'])
        self.assert_held(1, files)

    def test_c3_exact_top_level_keys_and_checked_fields(self) -> None:
        self.assert_held(1, self.edited('json', lambda d: d.update(note='<script>x</script>')))
        self.assert_held(1, self.edited('state', lambda s: s.update(extra=1)))
        self.assert_held(2, self.edited('json', lambda d: d.update(periodFrom='<b>')))
        self.assert_held(2, self.edited('json', lambda d: d.update(lagMonths=2)))
        self.assert_held(2, self.edited('json', lambda d: d.update(method=d['method'] + ' Extra words.')))
        self.assert_held(2, make_files(built='2026-11-05<script>'))
        self.assert_held(2, self.edited('state', lambda s: s.update(postcodeRelease='AUG 2026 <i>')))

    def test_c3_attribution_must_match_word_for_word(self) -> None:
        def attribution(change):
            return self.edited('json', lambda d: d.update(attribution=change(d['attribution'])))
        self.assert_held(8, attribution(lambda a: [a[0] + ' <script>alert(1)</script>', a[1]]))
        self.assert_held(8, attribution(lambda a: [a[0], a[1] + ' <!-- /district-table:attribution -->']))
        self.assert_held(8, attribution(lambda a: [a[0].replace('2026', '2025'), a[1]]))
        self.assert_held(8, attribution(lambda a: [a[1], a[0]]))

    def test_n3_a_number_cell_must_be_plain(self) -> None:
        for odd in ('2.5E5', '25_0000', ' 250000', '+250000'):
            self.assert_held(3, self.edited('csv', lambda t, odd=odd: t.replace(',250000,', f',{odd},', 1)))

    def test_n4_an_older_build_of_the_same_month_is_refused(self) -> None:
        self.assert_held(5, make_files(built='2026-11-04T12:00:00Z'), live_first=True)
        self.assert_held(5, make_files(built='2026-11-05T12:01:15Z'), live_first=True)   # BUILT less its fraction

    def test_w_a_figures_follow_their_counts(self) -> None:
        def regenerated(change):
            files = self.edited('json', change)
            files['table_latest.csv'] = table_csv(json.loads(files['table_latest.json'])['rows']).encode()
            return files
        rows = make_rows()
        shown = next(i for i, r in enumerate(rows) if r['median12m'] is not None)
        blank = next(i for i, r in enumerate(rows) if r['median12m'] is None)
        def row(i, **fields):
            return lambda d: d['rows'][i].update(fields)
        for change in (row(blank, median12m=123_000), row(shown, median12m=None), row(shown, upperQuartile12m=None),
                       row(shown, sales3m=4), row(blank, lowerQuartile12m=1), row(shown, lowSample=True),
                       row(blank, lowSample=False), row(blank, medianChangePct=1.5)):
            self.assert_held(7, regenerated(change))

    def test_a_broken_csv_quote_is_held_cleanly(self) -> None:
        self.assert_held(3, self.edited('csv', lambda t: t.replace('LS6', '"LS6', 1)))

    def test_c2_a_broken_page_template_writes_nothing(self) -> None:
        with SiteRoot() as root:
            page = root / site.PAGE
            page.write_text(page.read_text(encoding='utf-8').replace('<!-- /district-table:downloads -->', ''), encoding='utf-8')
            put_incoming(root, make_files())
            before = snapshot(root)
            code, result = run_site(root, '--publish', '--first-publish')
            self.assertEqual((code, result['code']), (3, 'template-broken'))
            self.assertEqual(snapshot(root), before)
            self.assertFalse((root / site.OUT).exists())

    def test_c2_a_half_archived_month_is_refused(self) -> None:
        with SiteRoot() as root:
            put_incoming(root, make_files())
            run_site(root, '--publish', '--first-publish')
            (root / site.OUT / 'district-medians-2026-10.json').unlink()
            put_incoming(root, make_files('2026-11', '2026-12-05T12:00:00Z'))
            before = snapshot(root)
            code, result = run_site(root, '--publish')
            self.assertEqual((code, result['status']), (2, 'refused'))
            self.assertEqual(snapshot(root), before)

    def test_refused_outside_this_repo(self) -> None:
        with SiteRoot() as root:
            (root / 'CNAME').write_text('example.com', encoding='utf-8')
            put_incoming(root, make_files())
            self.assertEqual(run_site(root, '--check', '--first-publish')[0], 2)

    def test_outputs_hold_no_postcode_beyond_the_district(self) -> None:
        with SiteRoot() as root:
            put_incoming(root, make_files())
            run_site(root, '--publish', '--first-publish')
            text = (root / site.OUT / 'district-medians-latest.csv').read_text(encoding='utf-8')
            self.assertNotRegex(text, r'\b[A-Z]{1,2}[0-9][0-9A-Z]? [0-9][A-Z]{2}\b')


# ------------------------------------------------------------------------------ the fetch

class FakeReply:
    def __init__(self, status: int, body: bytes) -> None:
        self.status, self._body = status, body

    def read(self, n: int) -> bytes:
        return self._body[:n]

    def __enter__(self) -> FakeReply:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class FakeOpener:
    """Answers record GETs from a dict; `script` overrides the answer for the n-th request (status, body)."""

    def __init__(self, files: dict[str, bytes], script: dict[int, tuple[int, bytes]] | None = None) -> None:
        self.files, self.script, self.seen = dict(files), script or {}, []

    def open(self, request, timeout: float) -> FakeReply:
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


class FetchRoot:
    """A temporary folder that passes the repo check (a CNAME of data.yappman.com)."""

    def __enter__(self) -> str:
        self.dir = tempfile.TemporaryDirectory()
        Path(self.dir.name, 'CNAME').write_text('data.yappman.com\n', encoding='utf-8')
        return self.dir.name

    def __exit__(self, *exc: object) -> None:
        self.dir.cleanup()


class FakeHTTPS(urllib.request.BaseHandler):
    """An https_open that answers without a socket, so the REAL opener (proxy, redirect and error handlers) runs."""

    def __init__(self, status: int, body: bytes = b'', headers: dict[str, str] | None = None) -> None:
        self.status, self.body, self.headers, self.seen = status, body, headers or {}, []

    def https_open(self, request):
        self.seen.append(request)
        message = email.message.Message()
        for key, value in self.headers.items():
            message[key] = value
        reply = urllib.response.addinfourl(io.BytesIO(self.body), message, request.full_url, self.status)
        reply.msg = 'x'
        return reply


def run_fetch(root: Path, opener: FakeOpener, *argv: str, reader=lambda: TOKEN) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = fetch.main(list(argv), reader=reader, opener=opener, root=root, sleep=lambda s: None)
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
            with self.assertRaises(fetch.FetchError):
                fetch.credential_token()

    def test_dry_run_reads_dt_state_only_and_saves_nothing(self) -> None:
        with FetchRoot() as tmp:
            opener = FakeOpener(make_files())
            code, out = run_fetch(Path(tmp), opener, '--dry-run')
            self.assertEqual(code, 0)
            self.assertEqual([r.full_url.rsplit('/', 1)[1] for r in opener.seen], ['DT_STATE'])
            result = json.loads(out)
            self.assertEqual((result['status'], result['state']['month'], result['state']['rows']), ('dry-run', '2026-10', 9))
            self.assertFalse((Path(tmp) / fetch.INCOMING).exists())

    def test_fetch_reads_three_keys_then_dt_state_again_and_saves(self) -> None:
        with FetchRoot() as tmp:
            files = make_files()
            opener = FakeOpener(files)
            code, out = run_fetch(Path(tmp), opener, '--fetch')
            self.assertEqual(code, 0, out)
            self.assertEqual([r.full_url.rsplit('/', 1)[1] for r in opener.seen],
                             ['DT_STATE', 'table_latest.json', 'table_latest.csv', 'DT_STATE'])
            for key, body in files.items():
                self.assertEqual((Path(tmp) / fetch.INCOMING / fetch.SAVED_AS[key]).read_bytes(), body)

    def test_every_request_is_a_get_with_the_token_in_the_header_only(self) -> None:
        with FetchRoot() as tmp:
            opener = FakeOpener(make_files())
            _, out = run_fetch(Path(tmp), opener, '--fetch')
            for request in opener.seen:
                self.assertEqual(request.get_method(), 'GET')
                self.assertEqual(request.get_header('Authorization'), 'Bearer ' + TOKEN)
                self.assertTrue(request.full_url.startswith(fetch.STORE_URL + '/records/'))
                self.assertNotIn(TOKEN, request.full_url)
                self.assertFalse(any(c in request.full_url for c in '?#%'))
                self.assertIsNone(request.data)
            self.assertNotIn(TOKEN, out)
            self.assertNotIn('pp-district-table', out)
            self.assertNotIn('key-value-stores', out)

    def test_dt_state_changed_during_the_fetch_saves_nothing(self) -> None:
        with FetchRoot() as tmp:
            later = make_files(built='2026-11-05T12:30:00Z')['DT_STATE']
            opener = FakeOpener(make_files(), script={4: (200, later)})
            code, out = run_fetch(Path(tmp), opener, '--fetch')
            self.assertEqual(code, 3)
            self.assertIn('state-changed-during-fetch', out)
            self.assertFalse((Path(tmp) / fetch.INCOMING).exists())

    def test_no_table_yet_and_wrong_version_stop(self) -> None:
        with FetchRoot() as tmp:
            self.assertEqual(run_fetch(Path(tmp), FakeOpener({}), '--dry-run')[0], 3)
            old = {'DT_STATE': json.dumps({'v': 1, 'month': '2026-10', 'builtAt': BUILT}).encode()}
            self.assertEqual(run_fetch(Path(tmp), FakeOpener(old), '--dry-run')[0], 3)

    def test_a_redirect_is_refused_and_not_followed(self) -> None:
        with FetchRoot() as tmp:
            opener = FakeOpener(make_files(), script={1: (302, b'')})
            code, out = run_fetch(Path(tmp), opener, '--dry-run')
            self.assertEqual(code, 4)
            self.assertIn('redirect-refused', out)
            self.assertEqual(len(opener.seen), 1)
            self.assertNotIn('body-with-detail', out)

    def test_a_4xx_is_not_retried_and_a_5xx_is(self) -> None:
        with FetchRoot() as tmp:
            opener = FakeOpener(make_files(), script={1: (401, b'')})
            code, out = run_fetch(Path(tmp), opener, '--dry-run')
            self.assertEqual((code, len(opener.seen), json.loads(out)['httpStatus']), (4, 1, 401))
            opener = FakeOpener(make_files(), script={1: (503, b''), 2: (503, b''), 3: (503, b'')})
            code, out = run_fetch(Path(tmp), opener, '--dry-run')
            self.assertEqual((code, len(opener.seen), json.loads(out)['code']), (4, 3, 'retries-exhausted'))

    def test_only_the_three_keys_can_be_requested(self) -> None:
        for key in ('PP_STATE', 'table_2026-10.json', '../records', 'DT_STATE?x=1', ''):
            with self.assertRaises(fetch.FetchError):
                fetch.record_url(key)

    def test_the_token_is_hidden_and_checked(self) -> None:
        secret = fetch.Secret(TOKEN)
        self.assertEqual((repr(secret), str(secret), f'{secret}'), ('<secret>',) * 3)
        out = io.StringIO()
        fetch.emit('leak ' + TOKEN, stream=out)
        self.assertNotIn(TOKEN, out.getvalue())
        for bad in ('has space inside', 'short', 'line\nbreak0000'):
            with self.assertRaises(fetch.FetchError):
                fetch.Secret(bad)
        with FetchRoot() as tmp:
            code, out = run_fetch(Path(tmp), FakeOpener({}), '--dry-run', reader=lambda: None)
            self.assertEqual((code, json.loads(out)['code']), (2, 'no-credential'))

    def test_the_real_opener_is_https_only_with_no_proxy(self) -> None:
        opener = fetch.build_opener(FakeHTTPS(200))
        self.assertEqual(set(opener.handle_open), {'https'})
        context = fetch.tls_context()
        self.assertIsNone(context.keylog_filename)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_the_real_opener_refuses_a_redirect(self) -> None:
        handler = FakeHTTPS(302, headers={'Location': 'https://elsewhere.example/steal'})
        with FetchRoot() as tmp:
            code, out = run_fetch(Path(tmp), fetch.build_opener(handler), '--dry-run')
        self.assertEqual((code, json.loads(out)['code']), (4, 'redirect-refused'))
        self.assertEqual(len(handler.seen), 1)
        self.assertNotIn('elsewhere', out)

    def test_the_real_opener_reads_a_record(self) -> None:
        handler = FakeHTTPS(200, make_files()['DT_STATE'])
        with FetchRoot() as tmp:
            code, out = run_fetch(Path(tmp), fetch.build_opener(handler), '--dry-run')
        self.assertEqual((code, json.loads(out)['state']['month']), (0, '2026-10'))
        self.assertEqual(handler.seen[0].get_header('Authorization'), 'Bearer ' + TOKEN)

    def test_an_oversize_response_is_refused(self) -> None:
        with FetchRoot() as tmp, mock.patch.object(fetch, 'MAX_RESPONSE_BYTES', 10):
            code, out = run_fetch(Path(tmp), FakeOpener(make_files()), '--dry-run')
        self.assertEqual((code, json.loads(out)['code']), (4, 'response-too-large'))

    def test_a_network_error_that_echoes_the_token_prints_only_a_code(self) -> None:
        class Leaky:
            def open(self, request, timeout):
                raise OSError('failed for ' + request.full_url + ' with ' + request.get_header('Authorization'))
        with FetchRoot() as tmp:
            code, out = run_fetch(Path(tmp), Leaky(), '--dry-run')
        self.assertEqual((code, json.loads(out)['code']), (4, 'network-failure'))
        self.assertNotIn(TOKEN, out)
        self.assertNotIn('pp-district-table', out)

    def test_inside_claude_code_a_fake_reader_alone_is_still_refused(self) -> None:
        with mock.patch.dict(os.environ, {'CLAUDECODE': '1'}), FetchRoot() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(fetch.main(['--dry-run'], reader=lambda: TOKEN, root=Path(tmp)), 2)
            self.assertIn('refused-inside-claude-code', out.getvalue())

    def test_refused_without_python_I_before_the_credential(self) -> None:
        with mock.patch.dict(os.environ, {}), FetchRoot() as tmp, \
                mock.patch.object(fetch, '_credential_api', side_effect=AssertionError('reached')), \
                mock.patch.object(sys, 'flags', mock.Mock(isolated=0)):
            os.environ.pop('CLAUDECODE', None)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(fetch.main(['--dry-run'], opener=FakeOpener(make_files()), root=Path(tmp)), 2)
            self.assertIn('run-with-python-I', out.getvalue())

    def test_refused_outside_this_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run_fetch(Path(tmp), FakeOpener(make_files()), '--fetch')
            self.assertEqual((code, json.loads(out)['code']), (2, 'not-the-data-yappman-repo'))
            self.assertFalse((Path(tmp) / fetch.INCOMING).exists())

    def test_fetch_then_build_end_to_end(self) -> None:
        with SiteRoot() as root:
            code, _ = run_fetch(root, FakeOpener(make_files()), '--fetch')
            self.assertEqual(code, 0)
            self.assertEqual(run_site(root, '--publish', '--first-publish')[0], 0)


if __name__ == '__main__':
    unittest.main(verbosity=1)
