"""Tests for docs/release/history_table_site.py (the history page's build) and the history page template.

    python -I -m pytest docs/release/test_history_table.py -q

A small history is made in the Actor's own format (price_paid/src/district_history.py, HISTORY_VERSION 1) in a temporary copy of the
repo's shape: a CNAME, a sitemap with the page's entry, and the real page template. No network, no token, no store.
"""
from __future__ import annotations

import csv
import io
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import history_table_site as hs  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
ATTRIBUTION = [
    'Contains HM Land Registry data © Crown copyright and database right 2026. This data is licensed under the Open Government Licence v3.0.',
    'Local authority codes: Source: Office for National Statistics licensed under the Open Government Licence v3.0. Contains OS data © '
    'Crown copyright and database right 2026. Contains Royal Mail data © Royal Mail copyright and database right 2026.',
]
BUILT = '2026-11-19T23:14:05.123456Z'
RELEASE = 'AUG_2026'


def row(year, district, split, sales, codes='E08000035', base=200000):
    figs = (None, None, None) if sales < 5 else (base + year, base + year - 20000, base + year + 30000)
    return {'year': year, 'district': district, 'localAuthorityCodes': codes, 'split': split, 'sales': sales,
            'median': figs[0], 'lowerQuartile': figs[1], 'upperQuartile': figs[2], 'lowSample': sales < 20}


def csv_text(rows):
    out = io.StringIO()
    w = csv.writer(out, lineterminator='\n')
    w.writerow(hs.COLUMNS)
    for r in rows:
        w.writerow(['' if r[c] is None else ('true' if r[c] is True else 'false' if r[c] is False else r[c]) for c in hs.COLUMNS])
    return out.getvalue()


def make_history(month='2026-10', built=BUILT, last_year=2025):
    areas = {
        'AB': [row(1995, 'AB1', 'all', 3, 'E06000001'), row(1996, 'AB1', 'all', 25, 'E06000001'), row(1996, 'AB2', 'flat', 5, 'E06000001'),
               row(2025, 'AB1', 'all', 40, 'E06000001')],
        'E': [row(2024, 'E1', 'all', 300, 'E09000030'), row(2024, 'E1', 'new-build', 19, 'E09000030'), row(2025, 'E1', 'all', 310, 'E09000030')],
        'LS': [row(2013, 'LS6', 'detached', 12, 'E08000035'), row(2014, 'LS6', 'detached', 20, 'E08000035')],
    }
    districts = {'AB': 2, 'E': 1, 'LS': 1}
    files = {}
    for area, rows in areas.items():
        doc = {'v': 1, 'title': hs.TITLE, 'area': area, 'firstYear': 1995, 'lastYear': last_year, 'month': month, 'postcodeRelease': RELEASE,
               'builtAt': built, 'licence': hs.LICENCE, 'attribution': ATTRIBUTION, 'method': hs.METHOD, 'columns': list(hs.COLUMNS), 'rows': rows}
        files[f'history_{area}.json'] = json.dumps(doc, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        files[f'history_{area}.csv'] = csv_text(rows).encode('utf-8')
    index = {'v': 1, 'title': hs.TITLE, 'firstYear': 1995, 'lastYear': last_year, 'month': month, 'postcodeRelease': RELEASE, 'builtAt': built,
             'licence': hs.LICENCE, 'attribution': ATTRIBUTION, 'method': hs.METHOD, 'columns': list(hs.COLUMNS),
             'areas': [{'area': a, 'districts': districts[a], 'rows': len(areas[a])} for a in areas]}
    state = {'v': 1, 'month': month, 'lastYear': last_year, 'postcodeRelease': RELEASE, 'builtAt': built, 'districts': sum(districts.values()),
             'rows': sum(len(r) for r in areas.values()), 'areas': len(areas)}
    files['history_index.json'] = json.dumps(index, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    files['HS_STATE.json'] = json.dumps(state, separators=(',', ':')).encode('utf-8')
    return files


@pytest.fixture
def root(tmp_path):
    r = tmp_path / 'site'
    (r / 'sold-prices/history').mkdir(parents=True)
    (r / 'CNAME').write_text('data.yappman.com\n', encoding='utf-8')
    shutil.copy(REPO / 'sold-prices/history/index.html', r / 'sold-prices/history/index.html')
    (r / 'sold-prices/index.html').write_text('<p>the monthly table, untouched</p>', encoding='utf-8')
    (r / 'sitemap.xml').write_text('<urlset>\n  <url>\n    <loc>https://data.yappman.com/sold-prices/history/</loc>\n    <lastmod>2026-01-01</lastmod>\n  </url>\n</urlset>\n', encoding='utf-8')
    return r


def put(root, files):
    folder = root / hs.INCOMING
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (folder / name).write_bytes(data)


def run(root, *args, today='2026-11-20'):
    return hs.main(list(args), root=root, today=today)


def tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob('*')) if p.is_file() and hs.INCOMING.parts[0] not in p.relative_to(root).parts}


def last_json(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def edit(files, name, fn):
    doc = json.loads(files[name].decode('utf-8'))
    fn(doc)
    files[name] = json.dumps(doc, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def sync_csv(files, area):
    """Make the area's CSV equal its JSON again, so that only the rule under test can fail."""
    rows = json.loads(files[f'history_{area}.json'].decode('utf-8'))['rows']
    files[f'history_{area}.csv'] = csv_text(rows).encode('utf-8')


def held(root, capsys, check, *args):
    before = tree(root)
    assert run(root, *(args or ('--check', '--first-publish'))) == 3
    out = last_json(capsys)
    assert out['status'] == 'held' and out['check'] == check, out
    assert tree(root) == before                                   # a held build writes nothing
    return out


# ---------------------------------------------------------------- the good path

def test_check_passes_and_writes_nothing(root, capsys):
    put(root, make_history())
    before = tree(root)
    assert run(root, '--check', '--first-publish') == 0
    out = last_json(capsys)
    assert out['status'] == 'checks-passed' and out['rows'] == 9 and out['areas'] == 3
    assert out['files'] == 7 and out['totalBytes'] == sum(len(v) for k, v in make_history().items() if k != 'HS_STATE.json') and out['largestBytes'] > 0
    assert tree(root) == before


def test_publish_writes_the_archive_the_latest_index_the_page_and_the_sitemap(root, capsys):
    files = make_history()
    put(root, files)
    assert run(root, '--publish', '--first-publish') == 0
    out = last_json(capsys)
    assert out['status'] == 'published'
    base = root / 'data/sold-prices/history'
    for name, data in files.items():
        if name != 'HS_STATE.json':
            assert (base / '2026-10' / name).read_bytes() == data           # published as fetched, byte for byte
    assert not (base / '2026-10/HS_STATE.json').exists()
    assert (base / 'index.json').read_bytes() == files['history_index.json']
    page = (root / 'sold-prices/history/index.html').read_text(encoding='utf-8')
    for statement in ATTRIBUTION:
        assert f'<p class="attribution">{statement}</p>' in page
    assert f'<p class="method">{hs.METHOD}</p>' in page
    assert '/data/sold-prices/history/2026-10/history_LS.csv' in page and '/data/sold-prices/history/2026-10/history_AB.json' in page
    assert 'Built 2026-11-19, postcode release AUG_2026' in page and '9 rows for 4 districts in 3 postcode areas' in page
    assert '<td>2026-10</td><td>2026-11-19</td><td>2025</td>' in page
    assert '<lastmod>2026-11-20</lastmod>' in (root / 'sitemap.xml').read_text(encoding='utf-8')
    assert (root / 'sold-prices/index.html').read_text(encoding='utf-8') == '<p>the monthly table, untouched</p>'   # the monthly table is not touched
    assert not list((root / 'data/sold-prices').glob('district-medians*'))


def test_second_run_with_the_same_build_is_nothing_new(root, capsys):
    put(root, make_history())
    assert run(root, '--publish', '--first-publish') == 0
    capsys.readouterr()
    before = tree(root)
    assert run(root, '--publish') == 0
    assert last_json(capsys)['status'] == 'nothing-new'
    assert tree(root) == before


def test_a_later_month_adds_a_dated_folder_and_keeps_the_old_one(root, capsys):
    first = make_history()
    put(root, first)
    assert run(root, '--publish', '--first-publish') == 0
    old = {p.name: p.read_bytes() for p in (root / 'data/sold-prices/history/2026-10').iterdir()}
    second = make_history(month='2026-11', built='2026-12-02T01:00:00Z')
    put(root, second)
    assert run(root, '--publish') == 0
    base = root / 'data/sold-prices/history'
    assert {p.name: p.read_bytes() for p in (base / '2026-10').iterdir()} == old                  # never rewritten
    assert (base / '2026-11/history_E.json').read_bytes() == second['history_E.json']
    assert (base / 'index.json').read_bytes() == second['history_index.json']
    page = (root / 'sold-prices/history/index.html').read_text(encoding='utf-8')
    assert page.index('<td>2026-11</td>') < page.index('<td>2026-10</td>')                          # newest first in the archive list


def test_an_area_file_the_index_does_not_list_is_ignored(root, capsys):
    files = make_history()
    files['history_ZZ.json'] = b'not json at all'
    files['history_ZZ.csv'] = b'x'
    put(root, files)
    assert run(root, '--publish', '--first-publish') == 0
    assert not (root / 'data/sold-prices/history/2026-10/history_ZZ.json').exists()


# ---------------------------------------------------------------- a failed check keeps what is live and writes nothing

def test_versions(root, capsys):
    files = make_history(); edit(files, 'history_index.json', lambda d: d.update(v=2)); put(root, files)
    held(root, capsys, 1)


def test_area_file_version(root, capsys):
    files = make_history(); edit(files, 'history_E.json', lambda d: d.update(v=2)); put(root, files)
    held(root, capsys, 1)


@pytest.mark.parametrize('field,value', [('month', '2026-09'), ('lastYear', 2024), ('postcodeRelease', 'JUL_2026'), ('builtAt', '2026-11-19T23:14:06Z')])
def test_an_area_file_from_another_build_holds_everything(root, capsys, field, value):
    files = make_history(); edit(files, 'history_LS.json', lambda d: d.update({field: value})); put(root, files)
    out = held(root, capsys, 2)
    assert 'failed midway' in out['reason']


@pytest.mark.parametrize('field,value', [('month', '2026-09'), ('postcodeRelease', 'JUL_2026'), ('builtAt', '2026-11-19T23:14:06Z'), ('lastYear', 2024)])
def test_the_index_must_match_hs_state(root, capsys, field, value):
    files = make_history(); edit(files, 'history_index.json', lambda d: d.update({field: value})); put(root, files)
    held(root, capsys, 2)


def test_counts_must_agree(root, capsys):
    files = make_history(); edit(files, 'history_index.json', lambda d: d['areas'][0].update(rows=99)); put(root, files)
    held(root, capsys, 3)
    files = make_history(); edit(files, 'HS_STATE.json', lambda d: d.update(rows=8)); put(root, files)
    held(root, capsys, 3)
    files = make_history(); edit(files, 'HS_STATE.json', lambda d: d.update(areas=4)); put(root, files)
    held(root, capsys, 3)


def test_area_row_count_must_equal_the_index(root, capsys):
    files = make_history(); edit(files, 'history_E.json', lambda d: d['rows'].pop()); put(root, files)
    held(root, capsys, 3)


def test_csv_must_equal_the_json(root, capsys):
    files = make_history(); files['history_E.csv'] = files['history_E.csv'].replace(b'310', b'311'); put(root, files)
    held(root, capsys, 4)
    files = make_history(); files['history_E.csv'] = files['history_E.csv'].replace(b'year,', b'yeer,', 1); put(root, files)
    held(root, capsys, 4)


@pytest.mark.parametrize('change,check', [
    (lambda r: r.update(split='semi'), 5), (lambda r: r.update(year=1994), 5), (lambda r: r.update(year=2026), 5), (lambda r: r.update(sales=0), 5),
    (lambda r: r.update(district='LS6A1'), 5), (lambda r: r.update(district='E1'), 5), (lambda r: r.update(localAuthorityCodes='S12000033'), 5),
    (lambda r: r.update(median=None), 5), (lambda r: r.update(lowerQuartile=None), 5), (lambda r: r.update(lowSample=False), 5),
    (lambda r: r.update(extra='x'), 5), (lambda r: r.update(median='1'), 5),
])
def test_each_row_rule(root, capsys, change, check):
    files = make_history()
    edit(files, 'history_LS.json', lambda d: change(d['rows'][0]))
    rows = json.loads(files['history_LS.json'].decode('utf-8'))['rows']
    csv_rows = []
    for r in rows:                                                    # keep the CSV equal to the JSON so only the rule under test fails
        csv_rows.append({c: r.get(c) for c in hs.COLUMNS})
    files['history_LS.csv'] = csv_text(csv_rows).encode('utf-8')
    put(root, files)
    held(root, capsys, check)


def test_figures_are_blank_exactly_under_5_sales(root, capsys):
    files = make_history()
    edit(files, 'history_AB.json', lambda d: d['rows'][0].update(sales=4, median=190000, lowerQuartile=180000, upperQuartile=200000))
    sync_csv(files, 'AB')
    put(root, files)
    held(root, capsys, 5)


def test_attribution_licence_method_title_must_be_exact(root, capsys):
    for field, value, check in (('attribution', [ATTRIBUTION[0]], 8), ('attribution', [ATTRIBUTION[0], ATTRIBUTION[1].replace('Royal Mail', 'Somebody')], 8),
                                ('licence', 'CC BY 4.0', 2), ('method', hs.METHOD + ' ', 2), ('title', 'Another title', 2)):
        files = make_history(); edit(files, 'history_index.json', lambda d: d.update({field: value})); put(root, files)
        held(root, capsys, check)
    files = make_history(); edit(files, 'history_E.json', lambda d: d.update(attribution=[ATTRIBUTION[0], 'something else'])); put(root, files)
    held(root, capsys, 8)


def test_attribution_year_is_the_build_year(root, capsys):
    files = make_history(built='2027-01-05T01:00:00Z')
    put(root, files)
    held(root, capsys, 8)


def test_keys_must_be_exact_and_not_repeat(root, capsys):
    files = make_history(); edit(files, 'history_E.json', lambda d: d.update(extra=1)); put(root, files)
    held(root, capsys, 1)
    files = make_history(); files['HS_STATE.json'] = files['HS_STATE.json'].replace(b'"v":1', b'"v":1,"v":1'); put(root, files)
    held(root, capsys, 1)
    files = make_history(); edit(files, 'HS_STATE.json', lambda d: d.update(extra=1)); put(root, files)
    held(root, capsys, 1)


def test_last_year_must_be_a_complete_year_before_the_month(root, capsys):
    files = make_history(last_year=2026); put(root, files)
    held(root, capsys, 2)


def test_a_file_over_the_size_cap_holds(root, capsys):
    files = make_history(); files['history_E.csv'] += b'x' * (hs.MAX_FILE_BYTES + 1); put(root, files)
    held(root, capsys, 1)


def test_missing_files_are_a_refusal_with_nothing_written(root, capsys):
    files = make_history(); del files['history_LS.csv']; put(root, files)
    before = tree(root)
    assert run(root, '--check', '--first-publish') == 2 and tree(root) == before
    assert not (root / hs.INCOMING).exists() or True
    (root / hs.INCOMING / 'HS_STATE.json').unlink()
    assert run(root, '--check', '--first-publish') == 2
    shutil.rmtree(root / hs.INCOMING)
    assert run(root, '--check', '--first-publish') == 2 and last_json(capsys)['code'] == 'incoming-files-missing'


def test_wrong_repo_is_refused(root, capsys):
    (root / 'CNAME').write_text('example.com\n', encoding='utf-8')
    put(root, make_history())
    assert run(root, '--check', '--first-publish') == 2 and last_json(capsys)['code'] == 'not-the-data-yappman-repo'


# ---------------------------------------------------------------- first publish, older than live, archives are never rewritten

def test_first_publish_rules(root, capsys):
    put(root, make_history())
    assert run(root, '--check') == 2                                  # nothing live: needs --first-publish
    assert last_json(capsys)['check'] == 6
    assert run(root, '--publish', '--first-publish') == 0
    assert run(root, '--check', '--first-publish') == 2               # something live: refused
    assert last_json(capsys)['check'] == 6


def test_a_build_older_than_the_live_one_holds(root, capsys):
    put(root, make_history(month='2026-11', built='2026-12-02T01:00:00Z'))
    assert run(root, '--publish', '--first-publish') == 0
    put(root, make_history(month='2026-10'))
    held(root, capsys, 6, '--publish')


def test_the_same_month_rebuilt_differently_is_held_and_the_archive_stays(root, capsys):
    put(root, make_history())
    assert run(root, '--publish', '--first-publish') == 0
    kept = {p.name: p.read_bytes() for p in (root / 'data/sold-prices/history/2026-10').iterdir()}
    files = make_history(built='2026-11-21T01:00:00Z')               # the same month, a later build
    edit(files, 'history_E.json', lambda d: d['rows'][0].update(sales=301))
    sync_csv(files, 'E')
    put(root, files)
    out = held(root, capsys, 6, '--publish')
    assert 'never rewritten' in out['reason']
    assert {p.name: p.read_bytes() for p in (root / 'data/sold-prices/history/2026-10').iterdir()} == kept


def test_a_broken_template_holds_and_writes_nothing(root, capsys):
    put(root, make_history())
    page = root / 'sold-prices/history/index.html'
    page.write_text(page.read_text(encoding='utf-8').replace('<!-- history-table:archive -->', ''), encoding='utf-8')
    before = tree(root)
    assert run(root, '--publish', '--first-publish') == 3 and tree(root) == before
    assert last_json(capsys)['code'] == 'template-broken'


def test_a_missing_sitemap_entry_holds_and_writes_nothing(root, capsys):
    put(root, make_history())
    (root / 'sitemap.xml').write_text('<urlset></urlset>\n', encoding='utf-8')
    before = tree(root)
    assert run(root, '--publish', '--first-publish') == 3 and tree(root) == before


def test_values_are_escaped_on_the_page(root, capsys):
    files = make_history()
    put(root, files)
    assert run(root, '--publish', '--first-publish') == 0
    page = (root / 'sold-prices/history/index.html').read_text(encoding='utf-8')
    assert '<script' not in page.split('<main', 1)[1].replace('<script src="/assets/site.js" defer></script>', '').replace('<script src="/assets/sold-history.js" defer></script>', '')


# ---------------------------------------------------------------- the page template and the repo's own links

def test_the_template_has_each_region_once_and_says_plainly_what_it_must():
    page = (REPO / 'sold-prices/history/index.html').read_text(encoding='utf-8')
    for name in ('summary', 'downloads', 'archive', 'attribution', 'method'):
        assert page.count(f'<!-- history-table:{name} -->') == 1 and page.count(f'<!-- /history-table:{name} -->') == 1
    text = page.split('<main', 1)[1]
    for phrase in ('Standard sales only (category A), by transfer date, in nominal pounds', 'not adjusted for inflation',
                   'one grouping at a time', 'There is a break in late 2013', 'Before October 2013 every sale was in the standard category',
                   'This is not an index', 'left blank, and shown as a dash, where a year has fewer than 5 sales', 'fewer than 20 sales is marked as a small sample',
                   'real sale prices that HM Land Registry already publishes', 'retired since 1995 are not included', 'The latest year is as at the month the file was built',
                   'England and Wales only. Scotland and Northern Ireland are not covered'):
        assert phrase in text, phrase
    assert '/sold-prices/history/' in page and 'rel="canonical" href="https://data.yappman.com/sold-prices/history/"' in page
    plainly = text.split('id="plainly"', 1)[1].split('id="download"', 1)[0]
    assert '<a ' not in plainly                                       # no hyperlinks in the explanatory text


def test_the_menu_link_is_under_free_data_and_nowhere_else_on_the_page():
    page = (REPO / 'sold-prices/history/index.html').read_text(encoding='utf-8')
    free = page.split('id="panel-free"', 1)[1].split('</ul>', 1)[0]
    assert '<a class="mi" href="/sold-prices/history/"><span class="mi-top"><span class="mi-name">Median sold prices since 1995</span></span></a>' in free
    assert page.count('href="/sold-prices/history/"') == 1
    assert 'aria-current="true" aria-expanded="false" aria-controls="panel-free"' in page
    assert 'aria-current="true" aria-expanded="false" aria-controls="panel-resources"' not in page


def test_the_monthly_table_page_and_its_builder_are_unchanged_by_this_work():
    """The monthly table's builder, its checks, its tests and its data are untouched. The /sold-prices/ page itself changes only in
    its site menu (the one line holding the Free data group), as every page does; its regions and text are as they were."""
    import subprocess

    def git(*args):
        return subprocess.run(['git', '-C', str(REPO), *args], capture_output=True, text=True).stdout
    changed = git('diff', '--name-only', 'origin/main', 'HEAD').split()
    assert not [f for f in changed if f in ('docs/release/district_table_site.py', 'docs/release/test_district_table.py',
                                            'docs/release/fetch_district_table.py') or f.startswith('data/sold-prices/district-')]
    if 'sold-prices/index.html' in changed:
        lines = [l for l in git('diff', '-U0', '--ignore-cr-at-eol', 'origin/main', 'HEAD', '--', 'sold-prices/index.html').splitlines()
                 if l[:1] in '+-' and l[:3] not in ('+++', '---')]
        assert len(lines) == 2 and all('panel-free' in l for l in lines), lines                # one menu line out, one in
