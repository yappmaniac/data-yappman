"""Tests of dvsa_ods.py on SYNTHETIC .ods files (dvsa_ods_fixture.py). No network, no real DVSA file.

    python -I -B -m unittest docs/release/test_dvsa_ods.py     (or: python -I -B docs/release/test_dvsa_ods.py)
"""

from __future__ import annotations

import io
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dvsa_ods as ods  # noqa: E402
from dvsa_ods_fixture import Date, Num, Rep, RepRow, content_xml, make_ods  # noqa: E402


class ReadOds(unittest.TestCase):
    def test_sheets_rows_and_cell_text(self) -> None:
        data = make_ods({
            'Contents': [['Table', 'What'], ['DRT122F', 'Waits']],
            'DRT122F': [['Country', 'Month'], ['England', Date('2019-01-01')], ['Wales', 'Jan 2019']],
        })
        sheets = ods.read_ods(data)
        self.assertEqual(list(sheets), ['Contents', 'DRT122F'])           # sheet order kept
        self.assertEqual(sheets['DRT122F'], [['Country', 'Month'], ['England', '2019-01-01'], ['Wales', 'Jan 2019']])

    def test_number_cells_give_the_raw_value_not_the_formatted_text(self) -> None:
        sheets = ods.read_ods(make_ods({'S': [[Num(1234, shown='1,234'), 7, 2.5, '1,234']]}))
        self.assertEqual(sheets['S'], [['1234', '7', '2.5', '1,234']])     # a TEXT cell keeps its comma

    def test_empty_cells_in_the_middle_are_kept_trailing_ones_dropped(self) -> None:
        sheets = ods.read_ods(make_ods({'S': [['a', None, 'c', None, None], [None, 'b']]}))
        self.assertEqual(sheets['S'], [['a', '', 'c'], ['', 'b']])

    def test_repeated_blank_filler_is_free(self) -> None:
        # what a spreadsheet writes after the data: a cell repeated 16,000 times and a row repeated a million times
        rows = [['a', Rep(None, 16000)], RepRow([Rep(None, 16000)], 1_000_000), ['b', 'c'], RepRow([None], 5_000_000)]
        sheets = ods.read_ods(make_ods({'S': rows}))
        self.assertEqual(sheets['S'], [['a'], ['b', 'c']])                  # the filler rows and cells were not expanded

    def test_repeated_non_empty_cell_and_row_are_expanded_within_limits(self) -> None:
        sheets = ods.read_ods(make_ods({'S': [[Rep('x', 3)], RepRow(['y'], 2)]}))
        self.assertEqual(sheets['S'], [['x', 'x', 'x'], ['y'], ['y']])
        with self.assertRaises(ods.OdsError) as caught:
            ods.read_ods(make_ods({'S': [[Rep('x', ods.MAX_COLS + 1)]]}))
        self.assertEqual(caught.exception.code, 'non-empty-cell-repeated-too-often')
        with self.assertRaises(ods.OdsError) as caught:
            ods.read_ods(make_ods({'S': [RepRow(['x'], 5000)]}))
        self.assertEqual(caught.exception.code, 'non-empty-row-repeated-too-often')

    def test_two_paragraphs_join_with_a_newline_and_spans_are_text(self) -> None:
        xml = ('<?xml version="1.0"?><office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
               'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
               '<office:body><office:spreadsheet><table:table table:name="S"><table:table-row>'
               '<table:table-cell office:value-type="string"><text:p>one <text:span>two</text:span></text:p><text:p>three</text:p>'
               '</table:table-cell></table:table-row></table:table></office:spreadsheet></office:body></office:document-content>')
        self.assertEqual(ods.read_ods(make_ods({}, raw_content=xml.encode()))['S'], [['one two\nthree']])


XML_HEAD = b'<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0">'


class Hostile(unittest.TestCase):
    def code(self, data: bytes) -> str:
        with self.assertRaises(ods.OdsError) as caught:
            ods.read_ods(data)
        return caught.exception.code

    def test_doctype_is_refused(self) -> None:
        self.assertEqual(self.code(make_ods({'S': [['a']]}, prefix='<!DOCTYPE x [<!ENTITY e "boom">]>')),
                         'doctype-or-entity-refused')

    def test_entity_bomb_is_refused_before_any_expansion(self) -> None:
        lol = ('<!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
               '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>')
        self.assertEqual(self.code(make_ods({'S': [['&c;']]}, prefix=lol)), 'doctype-or-entity-refused')

    def test_external_entity_is_refused(self) -> None:
        self.assertEqual(self.code(make_ods({'S': [['a']]}, prefix='<!DOCTYPE x SYSTEM "file:///etc/passwd">')),
                         'doctype-or-entity-refused')

    def test_oversize_member_is_refused_by_what_it_really_holds(self) -> None:
        old = ods.MAX_XML_BYTES, ods.MAX_RATIO
        ods.MAX_XML_BYTES, ods.MAX_RATIO = 2_000, 10_000_000
        try:
            data = make_ods({'S': [[f'cell number {i}'] for i in range(500)]})
            self.assertEqual(self.code(data), 'content-too-large')
        finally:
            ods.MAX_XML_BYTES, ods.MAX_RATIO = old

    def test_a_zip_bomb_ratio_is_refused(self) -> None:
        data = make_ods({'S': [['x' * 200]] * 3000})                          # tiny when compressed, large when read
        old = ods.MAX_RATIO
        ods.MAX_RATIO = 5
        try:
            self.assertEqual(self.code(data), 'content-too-large')
        finally:
            ods.MAX_RATIO = old

    def test_zip_over_the_size_cap(self) -> None:
        self.assertEqual(self.code(b'PK' + b'\0' * (ods.MAX_ZIP_BYTES + 1)), 'zip-too-large')

    def test_not_a_zip_and_no_content_xml(self) -> None:
        self.assertEqual(self.code(b'not a zip'), 'not-a-zip')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('other.xml', '<a/>')
        self.assertEqual(self.code(buffer.getvalue()), 'content-xml-not-single')

    def test_not_well_formed_and_wrong_root(self) -> None:
        self.assertEqual(self.code(make_ods({}, raw_content=XML_HEAD + b'<b></a></office:document-content>')), 'xml-not-well-formed')
        self.assertEqual(self.code(make_ods({}, raw_content=b'<a/>')), 'not-an-ods-content-file')

    def test_too_many_rows_and_columns(self) -> None:
        old = ods.MAX_ROWS
        ods.MAX_ROWS = 10
        try:
            self.assertEqual(self.code(make_ods({'S': [['a']] * 11})), 'too-many-cells-or-rows')
        finally:
            ods.MAX_ROWS = old
        self.assertEqual(self.code(make_ods({'S': [[str(i) for i in range(ods.MAX_COLS + 1)]]})), 'too-many-columns')

    def test_a_repeated_sheet_name_and_a_huge_repeat_count(self) -> None:
        body = content_xml({'S': [['a']]}).decode()
        twice = body.replace('</office:spreadsheet>', '<table:table table:name="S"><table:table-row/></table:table></office:spreadsheet>')
        self.assertEqual(self.code(make_ods({}, raw_content=twice.encode())), 'sheet-name-missing-repeated-or-too-many')
        bad = body.replace('<table:table-row>', '<table:table-row table:number-rows-repeated="99999999999">')
        self.assertEqual(self.code(make_ods({}, raw_content=bad.encode())), 'bad-repeat-count')

    def test_cell_text_cap(self) -> None:
        self.assertEqual(self.code(make_ods({'S': [['x' * (ods.MAX_TEXT + 10)]]})), 'cell-text-too-long')


if __name__ == '__main__':
    unittest.main()
