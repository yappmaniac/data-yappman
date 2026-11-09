"""Tests for the /this-week/ build. Fixtures and a temporary copy of the page only: no network, no token.

    python -I -B docs/release/test_this_week.py
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import district_table_site as dts  # noqa: E402
import this_week_site as tw  # noqa: E402

REPO = HERE.parent.parent
TODAY = date(2026, 11, 9)


def uk_records(vintage='2026-W44', published='2026-11-09T08:20:48Z', classes=None):
    base = {'vintage': vintage, 'publishedAt': published, 'revision': 1, 'status': 'ok'}
    classes = classes if classes is not None else [
        ('dairy-eggs', 1.9, 800), ('meat', 1.2, 900), ('fruit', 0.4, 500), ('bread-cereals', 2.6, 700), ('other', 9.9, 12),
        ('fish', -2.2, 300), ('oils-fats', -0.3, 250), ('vegetables', -1.1, 600), ('drinks', -4.0, 40)]
    rows = [dict(base, recordType='meta', title='UK Online Shelf-Price Index'),
            dict(base, recordType='headline', retailer='', **{'class': ''}, level=99.7238, weekOnWeekPct=-0.2409, matched=74335)]
    for name, wow, matched in classes:
        rows.append(dict(base, recordType='class', retailer='', level=100.5, weekOnWeekPct=wow, matched=matched, **{'class': name}))
    rows.append(dict(base, recordType='class', retailer='', level=90.0, weekOnWeekPct=50.0, matched=5000, **{'class': 'skipped'}) | {'status': 'skipped'})
    return rows


def basket(items_now=17, items_prev=17):
    def week(w, as_of, items, scale):
        return {'week': w, 'asOf': as_of, 'appliedAt': as_of + 'T05:45:42Z', 'commonItems': items,
                'commonTotal': {'tesco': 77.46 * scale, 'sainsburys': 65.51 * scale, 'asda': 65.11 * scale, 'aldi': 52.42 * scale}}
    return {'schema': 1, 'updated': '2026-11-06T05:45:54Z', 'gaps': [],
            'weeks': [week('2026-W44', '2026-11-01', items_prev, 1.0), week('2026-W45', '2026-11-06', items_now, 1.05)]}


def monthly(kind, built='2026-11-06T09:00:00Z', month='2026-10'):
    rows = []
    for n, value in enumerate((250000, 300000, 410000)):
        row = {'propertyType': 'all', 'district': f'LS{n + 1}'} if kind == 'sold' else {'propertyType': 'all', 'authorityCode': f'E0800003{n}'}
        row['median12m' if kind == 'sold' else 'grossYieldPct'] = value if kind == 'sold' else 4.0 + n
        rows.append(row)
    rows.append({'propertyType': 'flat', 'district': 'LS1', 'median12m': 1, 'authorityCode': 'E08000030', 'grossYieldPct': 9.9})
    rows.append({'propertyType': 'all', 'district': 'LS9', 'authorityCode': 'E08000039', 'median12m': None, 'grossYieldPct': None})
    return {'month': month, 'builtAt': built, 'rows': rows}


class Site:
    """A temporary root with the real page and sitemap and the fixture data."""

    def __init__(self, overrides=None):
        self.files = {tw.UK_JSON: uk_records(), tw.BASKET_JSON: basket(), tw.SOLD_JSON: monthly('sold'), tw.YIELD_JSON: monthly('yield')}
        self.files.update(overrides or {})

    def __enter__(self) -> Path:
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        (root / 'CNAME').write_text('data.yappman.com\n', encoding='utf-8')
        (root / 'this-week').mkdir()
        shutil.copy(REPO / 'this-week' / 'index.html', root / 'this-week' / 'index.html')
        shutil.copy(REPO / 'sitemap.xml', root / 'sitemap.xml')
        for relative, content in self.files.items():
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            (root / relative).write_text(content if isinstance(content, str) else json.dumps(content), encoding='utf-8')
        return root

    def __exit__(self, *exc) -> None:
        self.dir.cleanup()


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def run(root: Path, *argv: str, today: date = TODAY):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = tw.main(list(argv), root=root, today=today)
    return code, json.loads(out.getvalue())


def page(root: Path) -> str:
    return (root / tw.PAGE).read_text(encoding='utf-8')


class ThisWeekTests(unittest.TestCase):

    def test_check_writes_nothing_and_publish_fills_the_page(self) -> None:
        with Site() as root:
            before = snapshot(root)
            self.assertEqual(run(root, '--check')[1]['status'], 'checks-passed')
            self.assertEqual(snapshot(root), before)
            code, result = run(root, '--publish')
            self.assertEqual((code, result['status']), (0, 'published'))
            text = page(root)
            self.assertNotIn('No figures have been published here yet.', text)
            self.assertIn('Updated 2026-11-09.', text)
            self.assertIn('headline level is 99.72, -0.2% on the week before', text)
            self.assertIn('<loc>https://data.yappman.com/this-week/</loc>\n    <lastmod>2026-11-09</lastmod>',
                          (root / 'sitemap.xml').read_text(encoding='utf-8').replace('\r\n', '\n'))
            self.assertNotIn('official', text.lower())
            body = text.split('<main')[1].split('</main>')[0]
            self.assertNotRegex(body, r'\$\d|per 1,000')      # no Actor prices in the page body

    def test_category_moves_have_a_floor_and_ignore_skipped_records(self) -> None:
        with Site() as root:
            run(root, '--publish')
            text = page(root)
            rises = text.split('Largest category rises')[1].split('Largest category falls')[0]
            falls = text.split('Largest category falls')[1].split('<p class="attribution">')[0]
            self.assertEqual(re.findall(r'<td>([a-z ]+)</td><td>', rises), ['bread cereals', 'dairy eggs', 'meat'])
            self.assertEqual(re.findall(r'<td>([a-z ]+)</td><td>', falls), ['fish', 'vegetables', 'oils fats'])
            for left_out in ('other', 'drinks', 'skipped'):
                self.assertNotIn(f'<td>{left_out}</td>', text)
            self.assertIn('+2.6%', rises)
            self.assertIn('-2.2%', falls)

    def test_a_stale_source_says_so_and_shows_no_figures(self) -> None:
        old = uk_records(published='2026-10-20T08:00:00Z')
        with Site() as root:
            (root / tw.UK_JSON).write_text(json.dumps(old), encoding='utf-8')
            old_basket = basket()
            old_basket['weeks'][-1]['asOf'] = '2026-10-01'
            (root / tw.BASKET_JSON).write_text(json.dumps(old_basket), encoding='utf-8')
            run(root, '--publish')
            text = page(root)
            self.assertEqual(text.count('Not updated this week'), 2)
            self.assertNotIn('99.72', text)
            self.assertNotIn('Total for the common items', text)

    def test_the_basket_compares_only_like_for_like(self) -> None:
        with Site() as root:
            run(root, '--publish')
            text = page(root)
            self.assertIn('Against 2026-W44 (the same 17 items priced in common)', text)
            self.assertIn('Tesco: +3.87 (+5.0%)', text)
        with Site({tw.BASKET_JSON: basket(items_now=17, items_prev=18)}) as root:
            run(root, '--publish')
            text = page(root)
            self.assertIn('No comparison with 2026-W44: the items priced in common differ (17 against 18)', text)
            self.assertNotIn('Against 2026-W44', text)

    def test_monthly_tables_only_in_a_week_with_a_new_one(self) -> None:
        with Site() as root:
            run(root, '--publish')
            text = page(root)
            self.assertIn('new table for 2026-10', text)
            self.assertIn('4 districts, of which 3 have a 12-month median for all homes; the median of those medians is &pound;300,000', text)
            self.assertIn('4 authorities, of which 3 have an all-homes yield; the median of those yields is 5.0%', text)
        with Site({tw.SOLD_JSON: monthly('sold', built='2026-10-06T09:00:00Z'), tw.YIELD_JSON: monthly('yield', built='2026-10-06T09:00:00Z')}) as root:
            run(root, '--publish')
            self.assertIn('No new monthly table this week.', page(root))
        with Site({tw.YIELD_JSON: monthly('yield', built='2026-10-06T09:00:00Z')}) as root:
            run(root, '--publish')
            text = page(root)
            self.assertIn('Median sold prices by postcode district', text.split('Monthly tables')[1])
            self.assertNotIn('new table for 2026-10. 4 authorities', text)

    def assert_held(self, root: Path, check: int) -> None:
        before = snapshot(root)
        code, result = run(root, '--publish')
        self.assertEqual((code, result['status'], result.get('check')), (3, 'held', check), result)
        self.assertEqual(snapshot(root), before)

    def test_bad_sources_hold_the_page_and_write_nothing(self) -> None:
        bad_uk = uk_records()
        bad_uk[1]['level'] = 'high'
        with Site({tw.UK_JSON: bad_uk}) as root:
            self.assert_held(root, 2)
        with Site({tw.UK_JSON: [r for r in uk_records() if r['recordType'] != 'headline']}) as root:
            self.assert_held(root, 2)
        for mutate in (lambda b: b['weeks'][-1].update(commonItems='17'), lambda b: b['weeks'][-1]['commonTotal'].pop('aldi'),
                       lambda b: b['weeks'][-1]['commonTotal'].update(aldi=-1), lambda b: b['weeks'][-1].update(asOf='2026-11-31')):
            data = basket()
            mutate(data)
            with Site({tw.BASKET_JSON: data}) as root:
                self.assert_held(root, 2)
        for kind, key in (('sold', tw.SOLD_JSON), ('yield', tw.YIELD_JSON)):
            data = monthly(kind)
            data['builtAt'] = 'yesterday'
            with Site({key: data}) as root:
                self.assert_held(root, 2)
            with Site({key: monthly(kind) | {'rows': []}}) as root:
                self.assert_held(root, 2)
        with Site({tw.UK_JSON: '{not json'}) as root:
            self.assert_held(root, 1)
        with Site({tw.BASKET_JSON: '{"weeks": [], "weeks": []}'}) as root:       # a repeated key
            self.assert_held(root, 1)

    def test_a_broken_template_or_wrong_folder_writes_nothing(self) -> None:
        with Site() as root:
            p = root / tw.PAGE
            p.write_text(p.read_text(encoding='utf-8').replace('<!-- /district-table:uk -->', ''), encoding='utf-8')
            before = snapshot(root)
            code, result = run(root, '--publish')
            self.assertEqual((code, result['code']), (3, 'template-broken'))
            self.assertEqual(snapshot(root), before)
        with Site() as root:
            (root / 'CNAME').write_text('example.com', encoding='utf-8')
            self.assertEqual(run(root, '--check')[0], 2)

    def test_markup_in_a_source_value_is_held_not_published(self) -> None:
        bad = uk_records()
        bad.append(dict(bad[2], **{'class': '<script>alert(1)</script>', 'weekOnWeekPct': 9.0, 'matched': 900}))
        with Site({tw.UK_JSON: bad}) as root:
            self.assert_held(root, 2)
        bad_week = basket()
        bad_week['weeks'][-1]['week'] = '2026-W45<b>'
        with Site({tw.BASKET_JSON: bad_week}) as root:
            self.assert_held(root, 2)

    def test_the_pointers_are_the_sentences_on_their_source_pages(self) -> None:
        def plain(sentence: str) -> str:
            return re.sub(r'\?utm_source=[^"]*', '', sentence)
        for relative, sentence in tw.POINTERS:
            source = (REPO / relative).read_text(encoding='utf-8')
            self.assertIn('<p>' + plain(sentence) + '</p>', re.sub(r'\?utm_source=[^"]*', '', source), relative)
            self.assertIn('utm_campaign=this-week', sentence)

    def test_the_real_data_builds(self) -> None:
        """The committed data files and page, in a copy: every check passes on today's real figures."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in (tw.UK_JSON, tw.BASKET_JSON, tw.SOLD_JSON, tw.YIELD_JSON, tw.PAGE, dts.SITEMAP, Path('CNAME')):
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(REPO / relative, root / relative)
            code, result = run(root, '--check', today=date(2026, 11, 9))
            self.assertEqual((code, result['status']), (0, 'checks-passed'), result)


if __name__ == '__main__':
    unittest.main(verbosity=1)
