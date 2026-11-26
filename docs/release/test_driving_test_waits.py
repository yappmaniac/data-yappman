"""Tests of driving_test_waits.py on SYNTHETIC .ods files (invented numbers; the layout is an ASSUMPTION, see the module).

    python -I -B docs/release/test_driving_test_waits.py
"""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import driving_test_waits as dtw  # noqa: E402
from dvsa_ods_fixture import Date, Num, make_ods  # noqa: E402

CENTRE_HEAD = [t for _, t in dtw.CENTRE_HEADERS]
REGION_HEAD = [t for _, t in dtw.REGION_HEADERS]


def centre_row(country='England', region='London', centre='Alpha Town', month='2026-10', over=Num(120, '120'),
               tenpc=3, median=6.5, shares=(60, 25, 10, 5), window=Num(1500, '1,500'), booked=1200, avail=300):
    return [country, region, centre, Date(f'{month}-01') if isinstance(month, str) and len(month) == 7 else month,
            over, tenpc, median, *shares, window, booked, avail]


def centre_file(rows, *, head=None, extra_sheets=None, after=()):
    sheets = {'Contents': [['Table', 'Description'], ['DRT122F', 'Waits']], 'Notes': [['Some notes']]}
    sheets['DRT122F'] = [['DRT122F: invented title'], [], head or CENTRE_HEAD, *rows, *after]
    sheets.update(extra_sheets or {})
    return make_ods(sheets)


def parse(rows, **kw):
    return dtw.read_table(centre_file(rows, **kw), dtw.parse_centres)


class Centres(unittest.TestCase):
    def test_normal_month_and_thousands_commas(self) -> None:
        rows = parse([centre_row(window=Num(1500, '1,500'), over=Num(1234, '1,234')),
                      centre_row(centre='Beta Road', over='1,234', window='1,500')])
        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual((first.month, first.country, first.region, first.centre, first.centreStatus),
                         ('2026-10', 'England', 'London', 'Alpha Town', 'open'))
        self.assertEqual(first.centreKey, 'london.alpha-town')
        self.assertEqual(first.values['slotsInWindow'], 1500)                # a numeric cell
        self.assertEqual(rows[1].values['slotsInWindow'], 1500)              # a text cell "1,500"
        self.assertEqual(rows[1].values['slotsOvertime'], 1234)
        self.assertEqual(first.values['medianWaitWeeks'], 6.5)
        self.assertTrue(first.provisional)                                    # 2026-10 is after the April 2025 mark

    def test_a_pre_april_2025_month_is_not_provisional_and_month_formats(self) -> None:
        for text, expect in (('2019-01-01', '2019-01'), ('2019-01', '2019-01'), ('Jan 2019', '2019-01'),
                             ('January 2019', '2019-01'), ('Jan-19', '2019-01'), ('Sept 2024', '2024-09')):
            self.assertEqual(dtw.parse_month(text), expect)
        row = parse([centre_row(month='2025-03')])[0]
        self.assertFalse(row.provisional)
        self.assertTrue(parse([centre_row(month='2025-04')])[0].provisional)
        with self.assertRaises(dtw.LayoutError):
            dtw.parse_month('Smarch 2020')

    def test_redaction_codes_are_kept_not_imputed(self) -> None:
        row = parse([centre_row(median='[r]', shares=('[x]', '[n]', '[rv]', '[z]'), tenpc='')])[0]
        self.assertIsNone(row.values['medianWaitWeeks'])
        self.assertEqual(row.suppressed, {'medianWaitWeeks': 'r', 'shareWithin7Weeks': 'x', 'share7to14': 'n',
                                          'share14to21': 'rv', 'shareOver21': 'z'})
        self.assertIsNone(row.values['weeksTo10pcAvailability'])             # blank: no value, no code
        self.assertNotIn('weeksTo10pcAvailability', row.suppressed)

    def test_an_unknown_code_or_text_is_refused(self) -> None:
        for bad in ('[q]', 'n/a', '12 weeks', '[x', '1.2.3'):
            with self.assertRaises(dtw.LayoutError, msg=bad):
                parse([centre_row(median=bad)])

    def test_closed_centre_is_flagged_and_prefix_removed(self) -> None:
        row = parse([centre_row(centre='[z] Old Place')])[0]
        self.assertEqual((row.centre, row.centreStatus, row.centreKey), ('Old Place', 'closed', 'london.old-place'))

    def test_shares_must_be_percent_not_fraction_and_add_up(self) -> None:
        with self.assertRaises(dtw.LayoutError):
            parse([centre_row(shares=(0.6, 0.25, 0.1, 0.05))])                # fractions: sum 1, not 100
        with self.assertRaises(dtw.LayoutError):
            parse([centre_row(shares=(60, 25, 10, 20))])
        parse([centre_row(shares=(60, 25, 10, '[x]'))])                       # not all present: no sum check

    def test_range_checks(self) -> None:
        for kw in ({'median': -1}, {'median': 500}, {'booked': 1.5}, {'booked': -3}, {'avail': 5_000_000}):
            with self.assertRaises(dtw.LayoutError, msg=str(kw)):
                parse([centre_row(**kw)])

    def test_changed_header_stops_the_build(self) -> None:
        head = list(CENTRE_HEAD)
        head[6] = 'median wait (days)'
        with self.assertRaises(dtw.LayoutError) as caught:
            parse([centre_row()], head=head)
        self.assertIn('header row', caught.exception.reason)
        with self.assertRaises(dtw.LayoutError):
            parse([centre_row()], head=CENTRE_HEAD + ['A new band column'])
        with self.assertRaises(dtw.LayoutError):
            parse([centre_row()], head=CENTRE_HEAD[:-1])

    def test_header_note_marks_and_case_are_tolerated(self) -> None:
        head = [h.upper() + ' [note 3]' if i % 2 else f'  {h}  ' for i, h in enumerate(CENTRE_HEAD)]
        self.assertEqual(len(parse([centre_row()], head=head)), 1)

    def test_duplicate_centre_key_in_a_month_is_refused(self) -> None:
        with self.assertRaises(dtw.LayoutError) as caught:
            parse([centre_row(centre='Alpha Town'), centre_row(centre='ALPHA  TOWN')])    # same slug
        self.assertIn('twice', caught.exception.reason)
        parse([centre_row(month='2026-09'), centre_row(month='2026-10')])                  # different months are fine

    def test_unknown_country_blank_centre_and_total_row(self) -> None:
        with self.assertRaises(dtw.LayoutError):
            parse([centre_row(country='Narnia')])
        with self.assertRaises(dtw.LayoutError):
            parse([centre_row(centre='')])
        with self.assertRaises(dtw.LayoutError):
            parse([centre_row(centre='Total')[:2] + [''] + centre_row()[3:]])

    def test_notes_after_a_blank_row_are_fine_but_data_is_not(self) -> None:
        self.assertEqual(len(parse([centre_row()], after=[[], ['Source: invented note']])), 1)
        with self.assertRaises(dtw.LayoutError):
            parse([centre_row()], after=[[], centre_row(centre='Late')])

    def test_the_header_may_be_the_only_match_in_one_sheet(self) -> None:
        with self.assertRaises(dtw.LayoutError):
            parse([centre_row()], extra_sheets={'Copy': [CENTRE_HEAD, centre_row()]})
        with self.assertRaises(dtw.LayoutError):
            dtw.read_table(make_ods({'Contents': [['x']]}), dtw.parse_centres)

    def test_a_hostile_file_is_a_layout_error(self) -> None:
        with self.assertRaises(dtw.LayoutError) as caught:
            dtw.read_table(make_ods({'S': [['a']]}, prefix='<!DOCTYPE x [<!ENTITY e "1">]>'), dtw.parse_centres)
        self.assertIn('doctype-or-entity-refused', caught.exception.reason)


class Regions(unittest.TestCase):
    def test_region_table_and_great_britain_row(self) -> None:
        head = REGION_HEAD
        rows = [['England', 'London', Date('2026-10-01'), 100, 3, 7.0, 55, 25, 12, 8, 90_000, 70_000, 20_000],
                ['Great Britain', 'Great Britain', Date('2026-10-01'), 300, 3, 7.5, 50, 30, 12, 8, 400_000, 300_000, 100_000]]
        out = dtw.read_table(make_ods({'DRT121G': [head, *rows]}), dtw.parse_regions)
        self.assertEqual([r.region for r in out], ['London', 'Great Britain'])
        self.assertIsNone(out[0].centreKey)
        with self.assertRaises(dtw.LayoutError):
            dtw.read_table(make_ods({'DRT121G': [head, ['Mars', 'x', Date('2026-10-01')] + [1] * 10]}), dtw.parse_regions)


class National(unittest.TestCase):
    def test_quarterly_rows(self) -> None:
        head = [t for _, t in dtw.NATIONAL_HEADERS]
        out = dtw.read_table(make_ods({'DRT121A': [head, ['Q1 2026', Num(500000, '500,000'), 250000, 50.0],
                                                    ['Q2 2026', '[x]', '[x]', '[x]']]}), dtw.parse_national)
        self.assertEqual(out[0]['testsConducted'], 500000)
        self.assertEqual(out[1]['suppressed'], {'testsConducted': 'x', 'testsPassed': 'x', 'passRatePct': 'x'})
        with self.assertRaises(dtw.LayoutError):
            dtw.read_table(make_ods({'DRT121A': [head, ['Q1', 1, 1, 150]]}), dtw.parse_national)


class Derive(unittest.TestCase):
    def build(self, spec):
        """spec: list of (centre, month, median, status)"""
        rows = [dtw.WaitRow(m, 'England', 'London', f'london.{c}', c, st, {'medianWaitWeeks': med}) for c, m, med, st in spec]
        dtw.derive(rows)
        return {(r.centre, r.month): r for r in rows}

    def test_rank_one_is_the_longest_wait_ties_share_a_rank(self) -> None:
        got = self.build([('a', '2026-10', 8, 'open'), ('b', '2026-10', 12.5, 'open'), ('c', '2026-10', 8, 'open'),
                          ('d', '2026-10', 2, 'open')])
        self.assertEqual([got[(c, '2026-10')].rank for c in 'abcd'], [2, 1, 2, 4])

    def test_closed_centres_and_blank_medians_are_not_ranked(self) -> None:
        got = self.build([('a', '2026-10', 8, 'open'), ('b', '2026-10', 20, 'closed'), ('c', '2026-10', None, 'open')])
        self.assertEqual(got[('a', '2026-10')].rank, 1)
        self.assertIsNone(got[('b', '2026-10')].rank)
        self.assertIsNone(got[('c', '2026-10')].rank)

    def test_changes_come_from_the_same_centre_and_never_interpolate(self) -> None:
        got = self.build([('a', '2026-10', 10, 'open'), ('a', '2026-07', 7, 'open'), ('a', '2026-04', 12.5, 'open'),
                          ('a', '2025-10', 4, 'open'), ('b', '2026-10', 9, 'open'), ('b', '2026-08', 3, 'open')])
        a = got[('a', '2026-10')]
        self.assertEqual((a.change3m, a.change6m, a.change12m), (3.0, -2.5, 6.0))
        b = got[('b', '2026-10')]
        self.assertEqual((b.change3m, b.change6m, b.change12m), (None, None, None))   # 2026-07 etc. are missing for b
        self.assertIsNone(got[('a', '2025-10')].change3m)                              # nothing before it

    def test_a_centre_that_opens_has_no_change_and_exact_decimal_arithmetic(self) -> None:
        got = self.build([('a', '2026-10', 6.7, 'open'), ('a', '2026-07', 6.4, 'open')])
        self.assertEqual(got[('a', '2026-10')].change3m, 0.3)                          # Decimal, not 0.30000000000000071
        self.assertEqual(Decimal(str(got[('a', '2026-10')].change3m)), Decimal('0.3'))

    def test_month_minus(self) -> None:
        self.assertEqual(dtw.month_minus('2026-02', 3), '2025-11')
        self.assertEqual(dtw.month_minus('2026-12', 12), '2025-12')


if __name__ == '__main__':
    unittest.main()
