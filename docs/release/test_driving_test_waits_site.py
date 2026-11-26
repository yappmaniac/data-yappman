"""End-to-end tests of driving_test_waits_site.py on a SYNTHETIC repo skeleton and synthetic .ods files (invented numbers).

    python -I -B docs/release/test_driving_test_waits_site.py
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import driving_test_waits as dtw  # noqa: E402
import driving_test_waits_site as site  # noqa: E402
from dvsa_ods_fixture import Date, make_ods  # noqa: E402

REAL = site.REPO
NOW = datetime(2026, 11, 26, 19, 5, tzinfo=UTC)
CENTRES = [('England', 'London', 'Alpha Town'), ('England', 'London', 'Beta Road'), ('Scotland', 'Highlands', 'Gamma Glen'),
           ('Wales', 'Cymru', 'Delta Bay'), ('England', 'North West', 'Echo Park')]
AREAS = [('Country', 'Great Britain'), ('Country', 'England'), ('Country', 'Scotland'), ('Country', 'Wales'),
         ('Region', 'London'), ('Region', 'North West'), ('Region', 'Highlands'), ('Region', 'Cymru')]


def months(first='2019-01', last='2026-10'):
    month = first
    while month <= last:
        yield month
        month = dtw.month_minus(month, -1)


def numbers(ci: int, mi: int, bump: float = 0.0):
    median = 4 + ci * 1.5 + (mi % 7) * 0.5 + bump
    return [100 + mi, 3, median, 60, 25, 10, 5, 1500, 1200, 300, 20.0]


def centre_file(*, last='2026-10', skip=None, head=None, bump=0.0, closed_from='2026-01'):
    rows = []
    for mi, month in enumerate(months('2019-01', last)):
        if month == skip:
            continue
        for ci, (country, region, centre) in enumerate(CENTRES):
            name = f'[z] {centre}' if centre == 'Echo Park' and month >= closed_from else centre
            rows.append([country, region, name, Date(f'{month}-01'), *numbers(ci, mi, bump), '[z]'])
    return make_ods({'Cover_sheet': [['x']], 'Notes': [['n']],
                     'DRT122F': [['invented title'], ['one table'], ['shorthand'], head or [t for _, t in dtw.CENTRE_HEADERS], *rows]})


def region_file(last='2026-10'):
    rows = [[lv, ar, Date(f'{m}-01'), 1000 + mi, 500, 50.0, *numbers(ri, mi), '[z]']
            for mi, m in enumerate(months('2019-01', last)) for ri, (lv, ar) in enumerate(AREAS)]
    return make_ods({'DRT121G': [['invented title'], ['one table'], ['shorthand'], [t for _, t in dtw.REGION_HEADERS], *rows]})


def national_file():
    head = [t for _, t in dtw.NATIONAL_HEADERS]
    return make_ods({'DRT121A': [['invented title'], ['DRT121A'], ['one table'], ['In columns C and D'], ['shorthand'], head,
                                 ['Financial Quarter', '2026 to 2027 Q1 April to June', 500000, 250000, 50.0, '[z]'],
                                 ['Financial Year', '2025 to 2026', 1998621, 1000043, 50.0, '[z]']]})


def facts_for(files: dict[str, bytes], *, release='2026-11-11', updated='2026-11-13', read='2026-11-26T19:00:00Z') -> bytes:
    return json.dumps({'v': 1, 'releaseDate': release, 'lastUpdated': updated, 'readAt': read,
                       'files': {t: {'bytes': len(d), 'sha256': hashlib.sha256(d).hexdigest()} for t, d in files.items()}}).encode()


class Repo:
    """A temp copy of the three files the build touches, plus an _incoming folder."""

    def __init__(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix='dtw-test-'))
        (self.dir / 'CNAME').write_text('data.yappman.com\n')
        (self.dir / 'driving-test-wait-index').mkdir()
        shutil.copy(REAL / site.PAGE, self.dir / site.PAGE)
        shutil.copy(REAL / 'sitemap.xml', self.dir / 'sitemap.xml')

    def incoming(self, files: dict[str, bytes], facts: bytes | None = None) -> None:
        folder = self.dir / site.INCOMING
        folder.mkdir(parents=True, exist_ok=True)
        for table, data in files.items():
            (folder / site.FILES[table]).write_bytes(data)
        (folder / site.FACTS_FILE).write_bytes(facts if facts is not None else facts_for(files))

    def run(self, *args: str) -> tuple[int, dict]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(site, 'MIN_CENTRES', 3), mock.patch.object(site, 'MAX_CENTRES', 20):
            code = site.main(list(args), root=self.dir, today='2026-11-26', now=NOW)
        return code, json.loads(out.getvalue())

    def snapshot(self) -> dict[str, str]:
        return {str(p.relative_to(self.dir)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(self.dir.rglob('*')) if p.is_file() and '_incoming' not in p.parts}

    def read(self, relative: str) -> str:
        return (self.dir / relative).read_text(encoding='utf-8')

    def close(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


def good_files(**kw) -> dict[str, bytes]:
    return {'DRT122F': centre_file(**kw), 'DRT121G': region_file(kw.get('last', '2026-10')), 'DRT121A': national_file()}


class Publish(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Repo()
        self.addCleanup(self.repo.close)

    def test_first_publish_writes_the_files_the_page_and_the_sitemap(self) -> None:
        self.repo.incoming(good_files())
        code, result = self.repo.run('--publish', '--first-publish')
        self.assertEqual((code, result['status']), (0, 'published'), result)
        data = self.repo.dir / 'data/driving-test-waits'
        names = sorted(p.name for p in data.iterdir())
        for stem in site.DATASETS:
            self.assertIn(f'{stem}-latest.csv', names)
            self.assertIn(f'{stem}-latest.json', names)
            self.assertIn(f'{stem}-2026-10-dvsa-2026-11-11.csv', names)
            self.assertIn(f'{stem}-2026-10-dvsa-2026-11-11.json', names)
        self.assertIn('driving-test-waits.txt', names)
        self.assertFalse(any(n.endswith('.part') for n in names))
        self.assertIn('<lastmod>2026-11-26</lastmod>', self.repo.read('sitemap.xml').split('driving-test-wait-index/</loc>')[1][:60])

    def test_csv_holds_every_month_and_the_json_only_the_latest_24(self) -> None:
        self.repo.incoming(good_files())
        self.repo.run('--publish', '--first-publish')
        lines = self.repo.read('data/driving-test-waits/driving-test-waits-latest.csv').splitlines()
        header, body = lines[0].split(','), lines[1:]
        self.assertEqual(header, [n for n, _ in site.CENTRE_COLUMNS])
        self.assertEqual(len(body), 94 * len(CENTRES))                       # Jan 2019 to Oct 2026, five centres
        document = json.loads(self.repo.read('data/driving-test-waits/driving-test-waits-latest.json'))
        self.assertEqual({r['month'] for r in document['rows']}, set(months('2024-11', '2026-10')))
        self.assertEqual((document['month'], document['vintage'], document['rowsInCsv']), ('2026-10', '2026-11-11', len(body)))
        self.assertEqual(document['columns'], header)
        self.assertNotIn('index', document['title'].lower().replace('driving test waits in great britain, by test centre', ''))

    def test_values_ranks_changes_closed_and_codes_in_the_files(self) -> None:
        self.repo.incoming(good_files())
        self.repo.run('--publish', '--first-publish')
        document = json.loads(self.repo.read('data/driving-test-waits/driving-test-waits-latest.json'))
        last = {r['centre']: r for r in document['rows'] if r['month'] == '2026-10'}
        self.assertEqual(last['Echo Park']['centreStatus'], 'closed')       # closed from 2026-01, the [z] prefix removed
        self.assertIsNone(last['Echo Park']['rank'])
        ranks = sorted((r['rank'], c) for c, r in last.items() if r['rank'])
        self.assertEqual([c for _, c in ranks], ['Delta Bay', 'Gamma Glen', 'Beta Road', 'Alpha Town'])   # longest median first
        alpha = last['Alpha Town']
        mi = list(months()).index('2026-10')
        self.assertEqual(alpha['medianWaitWeeks'], 4 + (mi % 7) * 0.5)
        self.assertEqual(alpha['change12m'], (mi % 7) * 0.5 - ((mi - 12) % 7) * 0.5)
        self.assertTrue(alpha['provisional'])
        self.assertEqual(alpha['source'], 'DRT122F')
        self.assertEqual(alpha['licence'], 'OGL v3.0')

    def test_ogl_line_is_byte_exact_on_page_text_companion_json_and_json_ld(self) -> None:
        self.repo.incoming(good_files())
        self.repo.run('--publish', '--first-publish')
        line = 'Contains public sector information licensed under the Open Government Licence v3.0.'
        page = self.repo.read('driving-test-wait-index/index.html')
        self.assertIn(f'<p class="attribution">{line}</p>', page)
        self.assertIn(line, self.repo.read('data/driving-test-waits/driving-test-waits.txt'))
        for stem in site.DATASETS:
            self.assertIn(line, json.loads(self.repo.read(f'data/driving-test-waits/{stem}-latest.json'))['attribution'])
        block = re.search(r'<!-- driving-waits:jsonld -->\s*<script type="application/ld\+json">\n(.*?)\n</script>', page, re.S)
        ld = json.loads(block.group(1))
        self.assertEqual((ld['@type'], ld['license']), ('Dataset', 'https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/'))
        self.assertEqual(ld['citation'], site.ATTRIBUTION[1])
        self.assertIn('https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/', page)   # the page's own statement
        self.assertEqual(ld['temporalCoverage'], '2019-01-01/2026-10-31')
        self.assertIn('/data/driving-test-waits/driving-test-waits-latest.csv', {d['contentUrl'][len('https://data.yappman.com'):] for d in ld['distribution']})

    def test_page_text_title_headline_and_links(self) -> None:
        self.repo.incoming(good_files())
        self.repo.run('--publish', '--first-publish')
        page = self.repo.read('driving-test-wait-index/index.html')
        self.assertIn('<h1>Driving test waits in Great Britain, by test centre</h1>', page)
        self.assertIn('In October 2026, among the 4 open test centres', page)
        self.assertIn('not published by DVSA', page)
        self.assertNotRegex(page.lower(), r'wait index|median of medians|weighted')           # decision D3
        for href in re.findall(r'href="([^"]*)"', page):
            self.assertNotIn('?', href.replace('?utm', '') if href.startswith('https://apify.com') else href, href)
        self.assertEqual(len(re.findall(r'<tr><td>\d+</td><td>', page)), 4)                   # the four ranked open centres
        self.assertIn('Echo Park', self.repo.read('data/driving-test-waits/driving-test-waits-latest.csv'))
        self.assertNotIn('Echo Park', page.split('Regions, latest month')[0].split('Test centres, latest month')[1])   # closed: left out
        self.assertIn('1 centre DVSA shows as closed', page)

    def test_banned_words_are_nowhere_in_what_is_published(self) -> None:
        self.repo.incoming(good_files())
        self.repo.run('--publish', '--first-publish')
        banned = re.compile(r'(audit|verdict|genuine|cheapest|best|save[sd]?|official|accurate|accuracy|guarantee[ds]?)', re.I)
        text = [site.METHOD, site.DESCRIPTION, site.TITLE, *site.ATTRIBUTION, *(m for _, m in site.CENTRE_COLUMNS),
                *(n[1] for n in site.CENTRE_NOTES.values())]
        text.append(self.repo.read('driving-test-wait-index/index.html'))
        text.append(self.repo.read('data/driving-test-waits/driving-test-waits.txt'))
        for item in text:
            self.assertIsNone(banned.search(re.sub(r'<[^>]+>', ' ', item)), banned.search(re.sub(r'<[^>]+>', ' ', item)))

    def test_a_centre_with_a_note_gets_a_marker_in_the_headline_and_table_and_one_footnote(self) -> None:
        self.repo.incoming(good_files())
        with mock.patch.dict(site.CENTRE_NOTES, {'Delta Bay': ('note-delta', 'An invented lead sentence.')}, clear=True):
            self.repo.run('--publish', '--first-publish')
        page = self.repo.read('driving-test-wait-index/index.html')
        self.assertIn('Delta Bay<sup><a href="#note-delta">1</a></sup> (Cymru)', page)        # the headline (it has the longest wait)
        self.assertEqual(page.count('id="note-delta"'), 1)
        self.assertIn('<td>Delta Bay<sup><a href="#note-delta">1</a></sup></td>', page)       # and the table row
        # the figures in the note are computed from the data at build time (review finding 1)
        self.assertIn('An invented lead sentence. It has a row in 94 of the 94 months in this table (the first is January 2019), '
                      'and DVSA gives 1,500 standard test slots in the booking window for it in October 2026.', page)

    def test_the_note_figures_come_from_the_rows(self) -> None:
        def row(month, slots):
            return dtw.WaitRow(month, 'England', 'North West', 'north-west.x', 'X', 'open', {'slotsInWindow': slots})
        other = dtw.WaitRow('2019-01', 'England', 'London', 'london.y', 'Y', 'open', {'slotsInWindow': 5})
        rows = [other, row('2019-06', 3), row('2019-07', 0), row('2019-08', 401), row('2026-10', None)]
        text = site.note_text(rows, '2026-10', 'X', 'Lead.')
        self.assertEqual(text, 'Lead. It has a row in 4 of the 5 months in this table (the first is June 2019), '
                               'and DVSA gives no slot figures for it in October 2026.')
        rows[-1] = row('2026-10', 12)
        self.assertIn('and DVSA gives 12 standard test slots in the booking window for it in October 2026.', site.note_text(rows, '2026-10', 'X', 'Lead.'))
        rows = [other, row('2019-06', 3)]                                       # nothing for the latest month
        self.assertIn('and DVSA has no row for it in October 2026.', site.note_text(rows, '2026-10', 'X', 'Lead.'))
        with self.assertRaises(site.CheckFailed):                               # no rows at all: the figures cannot be computed
            site.note_text([other], '2026-10', 'X', 'Lead.')

    def test_the_real_note_says_only_what_dvsa_says_and_guesses_nothing(self) -> None:
        name, (anchor, lead) = next(iter(site.CENTRE_NOTES.items()))
        self.assertEqual((name, anchor), ('Carlisle LGV (Cars)', 'note-lgv-cars'))
        self.assertEqual(lead, 'DVSA lists Carlisle LGV (Cars) separately from Carlisle, and its notes do not explain the name.')
        for guess in ('few tests', 'lorry', 'suggests', 'our reading', 'not verified'):
            self.assertNotIn(guess, lead.lower())

    def test_json_ld_details(self) -> None:
        self.repo.incoming(good_files())
        self.repo.run('--publish', '--first-publish')
        page = self.repo.read('driving-test-wait-index/index.html')
        ld = json.loads(re.search(r'<!-- driving-waits:jsonld -->\s*<script type="application/ld\+json">\n(.*?)\n</script>', page, re.S).group(1))
        self.assertEqual(ld['temporalCoverage'], '2019-01-01/2026-10-31')                # the whole of October, as the site check needs a full date
        self.assertEqual(ld['citation'], site.ATTRIBUTION[1])                              # the source, not the licence line
        names = [v['name'] for v in ld['variableMeasured']]
        self.assertNotIn('source', names)
        self.assertNotIn('licence', names)
        self.assertNotIn('vintage', names)
        self.assertIn('medianWaitWeeks', names)
        self.assertIn('Open Government Licence v3.0', ld['description'])

    def test_display_precision_is_one_decimal_everywhere(self) -> None:
        self.repo.incoming(good_files())
        self.repo.run('--publish', '--first-publish')
        page = self.repo.read('driving-test-wait-index/index.html')
        centres = page.split('Test centres, latest month')[1].split('Regions, latest month')[0]
        self.assertIn('<td>60.0%</td>', centres)
        self.assertNotIn('<td>60%</td>', centres)
        self.assertRegex(centres, r'<td>\d+\.\d</td>|<td>\d+\.\d <span')                   # medians at 1 dp
        regions = page.split('Regions, latest month')[1].split('Tests conducted and passed')[0]
        self.assertIn('50.0%', regions)
        national = page.split('Tests conducted and passed, by quarter')[1].split('Method and source')[0]
        self.assertIn('50.0%', national)
        self.assertEqual(site._pct(44.2192), '44.2%')
        self.assertEqual(site._weeks(31.45), '31.5')                                       # half up
        self.assertEqual(site._weeks(0.04), '0.0')
        self.assertEqual(site._change(-0.04), '0.0')                                       # never "-0.0"
        self.assertEqual(site._change(1.26), '+1.3')

    def test_a_displayed_change_is_rounded_once_from_the_full_value(self) -> None:
        row = dtw.WaitRow('2026-10', 'England', 'London', 'london.a', 'a', 'open', {'medianWaitWeeks': 6.2457}, change3m=0.25)
        row.exact = {'change3m': dtw.Decimal('0.2457')}
        self.assertEqual(site._shown_change(row, 'change3m'), '+0.2')           # not +0.3, which rounding 0.25 again would give
        self.assertEqual(site._shown_change(row, 'change6m'), '&ndash;')
        self.assertEqual(site._change(0.25), '+0.3')                             # the plain formatter is unchanged

    def test_the_json_says_what_last_updated_means(self) -> None:
        self.repo.incoming(good_files())
        self.repo.run('--publish', '--first-publish')
        for stem in site.DATASETS:
            document = json.loads(self.repo.read(f'data/driving-test-waits/{stem}-latest.json'))
            self.assertEqual(document['lastUpdated'], '2026-11-13')
            self.assertIn('gov.uk', document['lastUpdatedMeans'])
            self.assertIn('not the date of the data', document['lastUpdatedMeans'])

    def test_llms_txt_carries_the_same_description_as_the_page(self) -> None:
        line = next(x for x in (REAL / 'llms.txt').read_text(encoding='utf-8').splitlines() if '/driving-test-wait-index/' in x)
        self.assertTrue(line.endswith(': ' + site.DESCRIPTION), line[-200:])
        self.assertNotIn('Free monthly', line)
        page = (REAL / site.PAGE).read_text(encoding='utf-8')
        self.assertIn(f'<meta name="description" content="{site.DESCRIPTION}">', page)

    def test_great_britain_comes_first_in_the_regions_table(self) -> None:
        self.repo.incoming(good_files())
        self.repo.run('--publish', '--first-publish')
        page = self.repo.read('driving-test-wait-index/index.html')
        body = page.split('Regions, latest month')[1].split('<tbody>')[1]
        rows = re.findall(r'<tr><td>([^<]*)</td>', body)
        self.assertEqual(rows[:4], ['Great Britain', 'England', 'Scotland', 'Wales'])

    def test_wording_about_the_update_cadence_and_the_gov_uk_date(self) -> None:
        self.repo.incoming(good_files())
        self.repo.run('--publish', '--first-publish')
        page = self.repo.read('driving-test-wait-index/index.html')
        self.assertIn('DVSA releases these figures monthly', page)
        self.assertNotIn('Updated monthly', page)                                           # a promise this page cannot make by itself
        self.assertIn('gov.uk page last updated 2026-11-13', page)
        self.assertNotIn('files last updated', page)
        self.assertIn('keeps one key, and changes are not adjusted for this', site.METHOD)   # a centre closed and reopened (finding 10)

    def test_check_writes_nothing(self) -> None:
        self.repo.incoming(good_files())
        before = self.repo.snapshot()
        code, result = self.repo.run('--check', '--first-publish')
        self.assertEqual((code, result['status']), (0, 'checks-passed'))
        self.assertEqual(self.repo.snapshot(), before)
        self.assertFalse((self.repo.dir / 'data').exists())

    def test_rerun_on_the_same_files_changes_nothing(self) -> None:
        self.repo.incoming(good_files())
        self.repo.run('--publish', '--first-publish')
        after_first = self.repo.snapshot()
        code, result = self.repo.run('--publish')
        self.assertEqual((code, result['status']), (0, 'nothing-new'), result)
        self.assertEqual(self.repo.snapshot(), after_first)

    def test_a_later_build_of_the_same_month_keeps_the_archive_and_updates_latest(self) -> None:
        self.repo.incoming(good_files())
        self.repo.run('--publish', '--first-publish')
        archive = 'data/driving-test-waits/driving-test-waits-2026-10-dvsa-2026-11-11.csv'
        first_archive = self.repo.read(archive)
        files = good_files(bump=0.5)                                          # a corrected file, read a little later
        self.repo.incoming(files, facts_for(files, read='2026-11-26T19:03:00Z'))
        code, result = self.repo.run('--publish')
        self.assertEqual((code, result['status']), (0, 'published'), result)
        self.assertEqual(self.repo.read(archive), first_archive)              # never rewritten
        self.assertNotEqual(self.repo.read('data/driving-test-waits/driving-test-waits-latest.csv'), first_archive)
        self.assertTrue(any('kept the driving-test-waits 2026-10 archive' in d for d in result['done']))

    def test_next_month_adds_an_archive_and_lists_both(self) -> None:
        self.repo.incoming(good_files())
        self.repo.run('--publish', '--first-publish')
        files = good_files(last='2026-11')
        self.repo.incoming(files, facts_for(files, release='2026-12-09', updated='2026-12-09', read='2026-12-09T19:00:00Z'))
        with mock.patch.object(site, 'MIN_CENTRES', 3):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), mock.patch.object(site, 'MAX_CENTRES', 20):
                code = site.main(['--publish'], root=self.repo.dir, today='2026-12-09', now=datetime(2026, 12, 9, 19, 5, tzinfo=UTC))
        self.assertEqual(code, 0, out.getvalue())
        page = self.repo.read('driving-test-wait-index/index.html')
        self.assertIn('driving-test-waits-2026-10-dvsa-2026-11-11.csv', page)
        self.assertIn('driving-test-waits-2026-11-dvsa-2026-12-09.csv', page)
        self.assertIn('In November 2026', page)


class Refusals(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Repo()
        self.addCleanup(self.repo.close)

    def assertHeld(self, code_wanted: int, files: dict[str, bytes], facts: bytes | None = None, *args: str, fragment: str = '') -> None:
        self.repo.incoming(files, facts)
        before = self.repo.snapshot()
        code, result = self.repo.run(*(args or ('--publish', '--first-publish')))
        self.assertEqual(code, code_wanted, result)
        self.assertIn(fragment, json.dumps(result))
        self.assertEqual(self.repo.snapshot(), before)                          # nothing written

    def test_a_changed_header_is_exit_3_and_writes_nothing(self) -> None:
        head = [t for _, t in dtw.CENTRE_HEADERS]
        head.insert(8, 'a new band column')
        self.assertHeld(3, good_files(head=head), None, fragment='header row')

    def test_a_missing_month_is_exit_3(self) -> None:
        self.assertHeld(3, good_files(skip='2022-05'), None, fragment='2022-05')

    def test_a_stale_release_is_exit_3(self) -> None:
        self.assertHeld(3, good_files(last='2026-09'), None, fragment='should end at 2026-10')

    def test_a_file_that_is_not_the_one_facts_describes_is_exit_3(self) -> None:
        files = good_files()
        facts = facts_for(files)
        files['DRT121A'] = national_file() + b'x'
        self.assertHeld(3, files, facts, fragment='not the file FACTS.json describes')

    def test_hostile_ods_is_exit_3(self) -> None:
        files = good_files()
        files['DRT121G'] = make_ods({'S': [['a']]}, prefix='<!DOCTYPE x [<!ENTITY e "1">]>')
        self.assertHeld(3, files, None, fragment='doctype-or-entity-refused')

    def test_missing_incoming_files_is_exit_2(self) -> None:
        code, result = self.repo.run('--check', '--first-publish')
        self.assertEqual((code, result['code']), (2, 'incoming-files-missing'))

    def test_first_publish_rules(self) -> None:
        self.repo.incoming(good_files())
        code, _ = self.repo.run('--publish')                                    # nothing live, no --first-publish
        self.assertEqual(code, 2)
        self.repo.run('--publish', '--first-publish')
        files = good_files(bump=1.0)
        self.repo.incoming(files, facts_for(files, read='2026-11-26T19:03:00Z'))
        code, _ = self.repo.run('--publish', '--first-publish')                 # something is live
        self.assertEqual(code, 2)

    def test_an_older_release_than_the_live_one_is_exit_3(self) -> None:
        self.repo.incoming(good_files())
        self.repo.run('--publish', '--first-publish')
        files = good_files(last='2026-09')
        self.repo.incoming(files, facts_for(files, release='2026-10-14', updated='2026-10-14', read='2026-10-14T19:00:00Z'))
        before = self.repo.snapshot()
        code, result = self.repo.run('--publish')
        self.assertEqual(code, 3, result)
        self.assertIn('older than the live one', result['reason'])
        self.assertEqual(self.repo.snapshot(), before)

    def test_a_leftover_part_file_is_refused(self) -> None:
        self.repo.incoming(good_files())
        data = self.repo.dir / 'data/driving-test-waits'
        data.mkdir(parents=True)
        (data / 'driving-test-waits-latest.csv.part').write_text('x')
        code, result = self.repo.run('--publish', '--first-publish')
        self.assertEqual((code, result['code']), (2, 'part-file-left-over'))

    def test_wrong_folder_is_refused(self) -> None:
        (self.repo.dir / 'CNAME').write_text('example.com\n')
        code, result = self.repo.run('--check')
        self.assertEqual((code, result['code']), (2, 'not-the-data-yappman-repo'))

    def test_broken_template_is_exit_3(self) -> None:
        self.repo.incoming(good_files())
        page = self.repo.dir / site.PAGE
        page.write_text(page.read_text(encoding='utf-8').replace('<!-- /driving-waits:method -->', ''), encoding='utf-8')
        code, result = self.repo.run('--check', '--first-publish')
        self.assertEqual((code, result['code']), (3, 'template-broken'))

    def test_describe_prints_sheet_names_and_only_the_first_four_rows(self) -> None:
        self.repo.incoming(good_files())
        code, result = self.repo.run('--describe')
        self.assertEqual((code, result['status']), (0, 'described'))
        sheets = result['tables']['DRT122F']
        self.assertEqual(set(sheets), {'Cover_sheet', 'Notes', 'DRT122F'})
        self.assertEqual(sheets['DRT122F']['rows'], 4 + 94 * len(CENTRES))
        self.assertLessEqual(len(sheets['DRT122F']['firstRows']), 4)


class RealTemplate(unittest.TestCase):
    """The committed page and sitemap are what the build expects."""

    def test_page_has_every_region_once_and_sitemap_has_one_entry(self) -> None:
        page = (REAL / site.PAGE).read_text(encoding='utf-8')
        for name in ('headline', 'summary', 'downloads', 'attribution', 'method', 'centres', 'regions', 'national', 'columns', 'jsonld'):
            self.assertEqual(page.count(f'<!-- driving-waits:{name} -->'), 1, name)
            self.assertEqual(page.count(f'<!-- /driving-waits:{name} -->'), 1, name)
        sitemap = (REAL / 'sitemap.xml').read_text(encoding='utf-8')
        self.assertEqual(sitemap.count('<loc>https://data.yappman.com/driving-test-wait-index/</loc>'), 1)
        self.assertIn('/driving-test-wait-index/', (REAL / 'llms.txt').read_text(encoding='utf-8'))
        self.assertIn('<link rel="canonical" href="https://data.yappman.com/driving-test-wait-index/">', page)
        self.assertNotIn('rental', page.lower().replace('/rental-yield/', '').replace('gross rental yield by local authority', ''))


if __name__ == '__main__':
    unittest.main()
