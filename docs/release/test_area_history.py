"""Tests for docs/release/area_history_site.py (the area history page's build) and the page template.

    python -I -m pytest docs/release/test_area_history.py -q

A SYNTHETIC area history is made in the Actor's own format (docs/release/area_history_fixture.py) in a temporary copy of the repo's shape:
a CNAME, a sitemap, llms.txt and the real page template. No network, no token, no store, and nothing is ever written to the real repo.
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import area_history_fixture as fx  # noqa: E402
import area_history_site as ah  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def make_root(tmp_path: Path) -> Path:
    root = tmp_path / 'site'
    (root / 'sold-prices/history/areas').mkdir(parents=True)
    (root / 'CNAME').write_text('data.yappman.com\n')
    shutil.copy(REPO / 'sold-prices/history/areas/index.html', root / 'sold-prices/history/areas/index.html')
    (root / 'sitemap.xml').write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset>\n  <url>\n    <loc>https://data.yappman.com/sold-prices/history/</loc>\n'
        '    <lastmod>2026-11-19</lastmod>\n  </url>\n  <url>\n    <loc>https://data.yappman.com/other/</loc>\n    <lastmod>2026-11-01</lastmod>\n  </url>\n</urlset>\n')
    (root / 'llms.txt').write_text('# Yappman Data\n\n- [History](https://data.yappman.com/sold-prices/history/): the district history.\n- [Other](https://data.yappman.com/other/): x.\n')
    return root


def put_incoming(root: Path, files: dict[str, bytes]) -> Path:
    folder = root / ah.INCOMING
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    for name, data in files.items():
        (folder / name).write_bytes(data)
    return folder


def run(root: Path, *argv: str, today: str = '2026-11-20') -> int:
    return ah.main(list(argv), root=root, today=today)


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    return make_root(tmp_path)


def edit_json(files: dict[str, bytes], name: str, mutate) -> None:
    doc = json.loads(files[name])
    mutate(doc)
    files[name] = json.dumps(doc, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def held(root: Path, files: dict[str, bytes], capsys, *argv: str) -> dict:
    put_incoming(root, files)
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file() and 'sold-prices-area-history' not in str(p)}
    code = run(root, '--publish', '--first-publish', *argv)
    out = json.loads(capsys.readouterr().out)
    assert code == 3 and out['status'] == 'held', out
    after = {p: p.read_bytes() for p in root.rglob('*') if p.is_file() and 'sold-prices-area-history' not in str(p)}
    assert before == after, 'a held build must write nothing'
    return out


def test_the_synthetic_fixture_passes_every_check(root, capsys):
    put_incoming(root, fx.make())
    assert run(root, '--check', '--first-publish') == 0
    out = json.loads(capsys.readouterr().out)
    assert out['status'] == 'checks-passed' and out['regions'] == 10 and out['filesShipped'] == 43 and out['filesFetched'] == 63
    assert out['notShippedBytes'] > 0 and out['unassignedSales'] == 786
    assert not (root / ah.OUT).exists(), '--check writes nothing'


def test_publish_writes_the_archive_the_latest_index_the_page_the_sitemap_and_llms_and_ships_quarters_as_csv_only(root, capsys):
    files = fx.make()
    put_incoming(root, files)
    assert run(root, '--publish', '--first-publish') == 0
    out = json.loads(capsys.readouterr().out)
    assert out['status'] == 'published'
    folder = root / ah.OUT / '2026-10'
    served = sorted(p.name for p in folder.iterdir())
    assert len(served) == 43 and 'ah_index.json' in served and 'ah_regions.json' in served and 'ah_regions.csv' in served
    for key in ah.expected_keys():
        if '_qtr_' in key:
            assert f'{key}.csv' in served and f'{key}.json' not in served
        else:
            assert f'{key}.csv' in served and f'{key}.json' in served
    for name in served:                                          # byte for byte as fetched
        assert (folder / name).read_bytes() == files[name]
    assert (root / ah.OUT / 'index.json').read_bytes() == files['ah_index.json']
    page = (root / ah.PAGE).read_text(encoding='utf-8')
    assert 'Latest build: 2026-10' in page and '786 sales' in page and 'quarters 1995-Q1 to 2026-Q2' in page
    for statement in json.loads(files['ah_index.json'])['attribution']:
        assert f'<p class="attribution">{statement}</p>' in page.replace('&#x27;', "'")
    assert page.count('href="/data/sold-prices/area-history/2026-10/ah_E12000001_year.csv"') == 1
    assert '_qtr_1995-2009.json' not in page
    sitemap = (root / 'sitemap.xml').read_text()
    assert sitemap.count('https://data.yappman.com/sold-prices/history/areas/') == 1 and '<lastmod>2026-11-20</lastmod>' in sitemap
    assert sitemap.index('/sold-prices/history/</loc>') < sitemap.index('/sold-prices/history/areas/</loc>') < sitemap.index('/other/</loc>')
    llms = (root / 'llms.txt').read_text()
    assert llms.count('(https://data.yappman.com/sold-prices/history/areas/)') == 1
    main = page[page.index('<main'):page.index('</main>')]
    import re
    links = re.findall(r'href="(https://apify\.com/[^"]*)"', main)
    assert 'fpr=' not in llms and len(links) <= 2                              # at most the two 'Maintained version' lines
    for u in links:
        assert u.split('?')[0] in ('https://apify.com/yappman/uk-property-listings', 'https://apify.com/yappman/uk-sold-house-prices-by-area')
        assert 'utm_campaign=sold-prices-areas' in u and 'fpr=' in u
        assert 'id="affiliate-disclosure"' in main and 'rel="sponsored"' in main


def test_a_second_run_with_the_same_files_does_nothing_and_a_newer_build_is_a_new_dated_folder(root, capsys):
    put_incoming(root, fx.make())
    assert run(root, '--publish', '--first-publish') == 0
    capsys.readouterr()
    assert run(root, '--publish') == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'nothing-new'
    put_incoming(root, fx.make(month='2026-12', built='2026-12-20T10:00:00Z', last_quarter='2026-Q3'))
    assert run(root, '--publish') == 0
    out = json.loads(capsys.readouterr().out)
    assert (root / ah.OUT / '2026-12').is_dir() and (root / ah.OUT / '2026-10').is_dir()
    assert json.loads((root / ah.OUT / 'index.json').read_text())['month'] == '2026-12'
    assert out['retention']['keep'] == ['2026-12'] and out['retention']['remove'] == ['2026-10']      # neither is a year-end vintage: only the latest is kept
    assert '2026-10' in (root / ah.PAGE).read_text() and '2026-12' in (root / ah.PAGE).read_text()


def test_retention_keeps_the_latest_and_one_year_end_vintage_and_never_deletes():
    def m(month, ly, lq):
        return {'month': month, 'lastYear': ly, 'lastQuarter': lq, 'bytes': 100}
    months = [m('2027-06', 2026, '2027-Q1'), m('2027-03', 2026, '2026-Q4'), m('2026-12', 2026, '2026-Q3'), m('2026-03', 2025, '2025-Q4'), m('2025-09', 2024, '2025-Q2')]
    r = ah.retention(months)
    assert r['keep'] == ['2027-06', '2027-03'] and r['remove'] == ['2026-12', '2026-03', '2025-09'] and r['removeBytes'] == 300
    assert ah.retention([m('2026-10', 2025, '2026-Q2')])['keep'] == ['2026-10']
    assert ah.retention([m('2027-03', 2026, '2026-Q4')])['remove'] == []


def test_an_archive_that_exists_and_differs_is_never_rewritten_and_an_older_build_is_held(root, capsys):
    put_incoming(root, fx.make())
    assert run(root, '--publish', '--first-publish') == 0
    capsys.readouterr()
    other = fx.make(built='2026-11-21T10:00:00Z')
    put_incoming(root, other)
    assert run(root, '--publish') == 3
    assert 'never rewritten' in json.loads(capsys.readouterr().out)['reason']
    put_incoming(root, fx.make(built='2026-11-19T10:00:00Z'))
    assert run(root, '--publish') == 3
    assert 'older than the live one' in json.loads(capsys.readouterr().out)['reason']


def test_first_publish_flag_rules(root, capsys):
    put_incoming(root, fx.make())
    assert run(root, '--publish') == 2                                   # nothing live: needs --first-publish
    assert json.loads(capsys.readouterr().out)['status'] == 'refused'
    assert run(root, '--publish', '--first-publish') == 0
    capsys.readouterr()
    put_incoming(root, fx.make(built='2026-11-21T10:00:00Z', month='2026-11'))
    assert run(root, '--publish', '--first-publish') == 2                # something is live


MUTATIONS = {
    'state version': lambda f: edit_json(f, 'AH_STATE.json', lambda d: d.update(v=2)),
    'index version': lambda f: edit_json(f, 'ah_index.json', lambda d: d.update(v=2)),
    'file version': lambda f: edit_json(f, 'ah_E12000001_year.json', lambda d: d.update(v=2)),
    'lookup hash not hex': lambda f: edit_json(f, 'AH_STATE.json', lambda d: d.update(regionLookupSha256='xyz')),
    'builtAt differs in one file': lambda f: edit_json(f, 'ah_E12000002_year.json', lambda d: d.update(builtAt='2026-11-20T11:00:00Z')),
    'lastQuarter differs in a quarterly file': lambda f: edit_json(f, 'ah_E12000003_qtr_2010-onwards.json', lambda d: d.update(lastQuarter='2026-Q1')),
    'postcodeRelease differs in index': lambda f: edit_json(f, 'ah_index.json', lambda d: d.update(postcodeRelease='SEP_2026')),
    'state rows differs': lambda f: edit_json(f, 'AH_STATE.json', lambda d: d.update(rows=d['rows'] + 1)),
    'totals files differs': lambda f: edit_json(f, 'ah_index.json', lambda d: d['totals'].update(files=30)),
    'row count differs from the index': lambda f: edit_json(f, 'ah_index.json', lambda d: d['files'][0].update(rows=d['files'][0]['rows'] + 1)),
    'an unknown extra file in the index': lambda f: edit_json(f, 'ah_index.json', lambda d: d['files'].append(dict(d['files'][0], key='ah_E12000001_year2'))),
    'attribution changed': lambda f: edit_json(f, 'ah_index.json', lambda d: d['attribution'].__setitem__(2, 'Region lookup: other.')),
    'a fourth attribution statement': lambda f: edit_json(f, 'ah_index.json', lambda d: d['attribution'].append('x')),
    'licence changed': lambda f: edit_json(f, 'ah_index.json', lambda d: d.update(licence='Open Government Licence v2.0')),
    'method changed': lambda f: edit_json(f, 'ah_index.json', lambda d: d.update(method=d['method'] + ' Extra.')),
    'period outside the years': lambda f: edit_json(f, 'ah_E12000001_year.json', lambda d: d['rows'][0].update(period='2026')),
    'quarter after lastQuarter': lambda f: edit_json(f, 'ah_E12000001_qtr_2010-onwards.json', lambda d: d['rows'][-1].update(period='2026-Q3')),
    'quarter in the wrong block': lambda f: edit_json(f, 'ah_E12000001_qtr_1995-2009.json', lambda d: d['rows'][0].update(period='2012-Q1')),
    'year split on a quarter row': lambda f: edit_json(f, 'ah_E12000001_qtr_2010-onwards.json', lambda d: d['rows'][0].update(split='freehold')),
    'bad authority code': lambda f: edit_json(f, 'ah_E12000001_year.json', lambda d: d['rows'][0].update(code='E05000001')),
    'welsh authority in England': lambda f: edit_json(f, 'ah_E12000001_year.json', lambda d: d['rows'][0].update(code='W06000001')),
    'bad region code': lambda f: edit_json(f, 'ah_regions.json', lambda d: d['rows'][0].update(code='E12000010')),
    'wrong geography in a file': lambda f: edit_json(f, 'ah_E12000001_year.json', lambda d: d['rows'][0].update(geography='region')),
    'sales zero': lambda f: edit_json(f, 'ah_E12000001_year.json', lambda d: d['rows'][0].update(sales=0)),
    'figure shown under 5 sales': lambda f: edit_json(f, 'ah_E12000001_year.json', lambda d: d['rows'][0].update(median=1)),
    'figure blank at 5 or more sales': lambda f: edit_json(f, 'ah_E12000001_year.json', lambda d: d['rows'][2].update(median=None)),
    'lowSample wrong': lambda f: edit_json(f, 'ah_E12000001_year.json', lambda d: d['rows'][0].update(lowSample=False)),
    'name with a formula start': lambda f: edit_json(f, 'ah_E12000001_year.json', lambda d: d['rows'][0].update(name='=HYPERLINK("x")')),
    'region sales do not equal the sum of its authorities': lambda f: edit_json(f, 'ah_regions.json', lambda d: d['rows'][5].update(sales=d['rows'][5]['sales'] + 1)),
    'a row missing from the region file': lambda f: edit_json(f, 'ah_regions.json', lambda d: d['rows'].pop()),
    'wales is not Wales': lambda f: edit_json(f, 'ah_index.json', lambda d: [e.update(regionName='Cymru') for e in d['files'] if e['region'] == 'W92000004']),
    'an extra field in a row': lambda f: edit_json(f, 'ah_E12000001_year.json', lambda d: d['rows'][0].update(extra=1)),
    'a duplicate JSON key': lambda f: f.update({'ah_E12000001_year.json': f['ah_E12000001_year.json'].replace(b'"v":1', b'"v":1,"v":1', 1)}),
    'CSV cell differs from JSON': lambda f: f.update({'ah_E12000004_year.csv': f['ah_E12000004_year.csv'].replace(b',2014,', b',2015,', 1)}),
    'CSV header differs': lambda f: f.update({'ah_E12000004_year.csv': f['ah_E12000004_year.csv'].replace(b'periodType', b'type', 1)}),
    'CSV has a row too many': lambda f: f.update({'ah_E12000004_qtr_2010-onwards.csv': f['ah_E12000004_qtr_2010-onwards.csv'] + b'quarter,2026-Q2,authority,E06000401,Alpha Borough,all,1,,,,true\n'}),
}


@pytest.mark.parametrize('name', sorted(MUTATIONS))
def test_every_check_holds_the_build_and_writes_nothing(root, capsys, name):
    files = fx.make()
    MUTATIONS[name](files)
    out = held(root, files, capsys)
    assert 'check' in out or out.get('code') == 'template-broken'


def test_unknown_extra_fields_in_the_state_index_entries_totals_and_documents_are_ignored_but_a_missing_one_holds(root, capsys):
    files = fx.make()
    edit_json(files, 'AH_STATE.json', lambda d: d.update(buildKind='incremental', chainLength=2))
    edit_json(files, 'ah_index.json', lambda d: (d.update(lastFullBuildAt='2026-11-01T00:00:00Z'), d['totals'].update(unassignedByYear={'2025': 1}),
                                                  d['files'][0].update(yearDigests={'1995': 'x'})))
    edit_json(files, 'ah_E12000001_year.json', lambda d: d.update(reusedBefore='2024'))
    put_incoming(root, files)
    assert run(root, '--check', '--first-publish') == 0
    capsys.readouterr()
    missing = fx.make()
    edit_json(missing, 'AH_STATE.json', lambda d: d.pop('lastQuarter'))
    held(root, missing, capsys)


def test_the_incremental_method_sentence_is_accepted_when_every_file_carries_it_and_shown_on_the_page(root, capsys):
    files = fx.make()
    for name in [n for n in files if n.endswith('.json') and n != 'AH_STATE.json']:
        edit_json(files, name, lambda d: d.update(method=ah.METHOD_INCREMENTAL))
    put_incoming(root, files)
    assert run(root, '--publish', '--first-publish') == 0
    assert 'lastFullBuildAt in the index' in (root / ah.PAGE).read_text(encoding='utf-8')
    capsys.readouterr()
    mixed = fx.make()
    edit_json(mixed, 'ah_index.json', lambda d: d.update(method=ah.METHOD_INCREMENTAL))       # the files still carry the other sentence
    held(make_root(root.parent / 'second'), mixed, capsys)


def test_a_file_missing_from_the_folder_is_refused_with_nothing_written(root, capsys):
    files = fx.make()
    del files['ah_E12000005_qtr_1995-2009.csv']
    put_incoming(root, files)
    assert run(root, '--publish', '--first-publish') == 2
    assert json.loads(capsys.readouterr().out)['status'] == 'refused'
    assert not (root / ah.OUT).exists()


def test_files_the_index_does_not_list_are_ignored_and_never_published(root, capsys):
    files = fx.make()
    files['ah_E12000001_year_old.json'] = b'{"not": "listed"}'
    files['ah_E12000001_year_old.csv'] = b'x'
    put_incoming(root, files)
    assert run(root, '--publish', '--first-publish') == 0
    assert not list((root / ah.OUT / '2026-10').glob('*_old.*'))


def test_a_file_over_the_size_cap_is_held(root, capsys):
    files = fx.make()
    files['ah_E12000001_year.csv'] = files['ah_E12000001_year.csv'] + b'#' * 8_000_001
    held(root, files, capsys)


def test_a_broken_page_template_or_a_missing_sitemap_entry_point_holds_the_build(root, capsys):
    page = root / ah.PAGE
    page.write_text(page.read_text(encoding='utf-8').replace('<!-- area-history:method -->', ''), encoding='utf-8')
    out = held(root, fx.make(), capsys)
    assert out['code'] == 'template-broken'


def test_the_wrong_folder_is_refused(tmp_path, capsys):
    other = tmp_path / 'other'
    other.mkdir()
    assert ah.main(['--check', '--first-publish'], root=other) == 2
    assert 'not-the-data-yappman-repo' in capsys.readouterr().out


def test_a_source_folder_outside_the_repo_is_refused(root, tmp_path, capsys):
    outside = tmp_path / 'outside'
    outside.mkdir()
    assert run(root, '--check', '--first-publish', '--from', str(outside)) == 2


def test_the_page_template_has_each_region_once_the_picker_ids_and_no_links_in_the_text():
    page = (REPO / ah.PAGE).read_text(encoding='utf-8')
    for name in ('summary', 'downloads', 'attribution', 'method', 'archive', 'unassigned'):
        assert page.count(f'<!-- area-history:{name} -->') == 1 and page.count(f'<!-- /area-history:{name} -->') == 1
    for ident in ('sa-app', 'sa-region', 'sa-area', 'sa-period', 'sa-split', 'sa-table', 'sa-body', 'sa-status', 'sa-files', 'sa-caption', 'sa-period-head'):
        assert f'id="{ident}"' in page
    body = page[page.index('<main'):page.index('</main>')]
    assert '<a ' not in body.replace('<!-- area-history:downloads -->', '').split('<h2 id="download">')[0], 'no hyperlinks in the body text above the downloads'
    assert '/assets/sold-areas.js' in page and '/assets/sold-history.js' not in page
    assert 'Compare across 2013 with care' in page and 'category A' in page and 'not combined' in page and 'not an index' in page.lower()
    assert 'site:nav active=free' in page and '<!-- site:footer -->' in page


def test_the_says_plainly_list_covers_every_required_statement():
    page = (REPO / ah.PAGE).read_text(encoding='utf-8')
    for phrase in ('Standard sales only (category A)', 'nominal pounds', 'one grouping at a time', 'Quarters have all sales and the four property types only',
                   'break in late 2013', 'This is not an index', 'today&rsquo;s authorities applied back to 1995', 'in no area',
                   'nine English regions', 'Wales is shown as one area', 'fewer than 5 sales', 'fewer than 20 sales', 'exactly 5 sales',
                   'as at the month the file was built'):
        assert phrase in page, phrase


def test_the_builder_imports_nothing_that_reaches_a_network_or_runs_a_program():
    import re
    src = Path(ah.__file__).read_text(encoding='utf-8')
    src = src[src.index('from __future__'):]
    modules = set(re.findall(r'^(?:from|import) ([a-z_]+)', src, flags=re.M))
    assert modules <= {'__future__', 'argparse', 'csv', 'html', 'io', 'json', 're', 'sys', 'collections', 'dataclasses', 'datetime', 'pathlib', 'typing',
                       'district_table_site'}, modules
    for banned in ('eval(', 'exec(', 'os.system', 'APIFY'):
        assert banned not in src, banned
