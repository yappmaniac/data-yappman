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

    def cell_xml(self, inner: str, cell_attrs: str = 'office:value-type="string"') -> bytes:
        return make_ods({}, raw_content=(
            '<?xml version="1.0"?><office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
            '<office:body><office:spreadsheet><table:table table:name="S"><table:table-row>'
            f'<table:table-cell {cell_attrs}>{inner}</table:table-cell></table:table-row></table:table>'
            '</office:spreadsheet></office:body></office:document-content>').encode())

    def test_the_text_cap_holds_for_spaces_tabs_and_line_breaks(self) -> None:
        # each of these adds text without a character-data event, so they were not counted before (review finding 2)
        flood = '<text:p>' + '<text:s text:c="200"/>' * 30 + '</text:p>'               # 6,000 spaces
        self.assertEqual(self.code(self.cell_xml(flood)), 'cell-text-too-long')
        self.assertEqual(self.code(self.cell_xml('<text:p>' + '<text:tab/>' * (ods.MAX_TEXT + 1) + '</text:p>')), 'cell-text-too-long')
        self.assertEqual(self.code(self.cell_xml('<text:p>' + '<text:line-break/>' * (ods.MAX_TEXT + 1) + '</text:p>')), 'cell-text-too-long')

    def test_the_text_cap_holds_for_the_joined_text_of_many_paragraphs(self) -> None:
        many = '<text:p>' + 'x' * 500 + '</text:p>'
        self.assertEqual(self.code(self.cell_xml(many * 5)), 'cell-text-too-long')            # 2,500 chars in all
        self.assertEqual(self.code(self.cell_xml('<text:p>a</text:p>' * (ods.MAX_PARAGRAPHS + 1))), 'cell-text-too-long')
        self.assertEqual(ods.read_ods(self.cell_xml(many * 2))['S'], [['x' * 500 + '\n' + 'x' * 500]])   # under the cap is fine

    def test_the_text_cap_holds_for_an_attribute_value(self) -> None:
        long_value = 'y' * (ods.MAX_TEXT + 1)
        self.assertEqual(self.code(self.cell_xml('', f'office:value-type="string" office:string-value="{long_value}"')), 'cell-text-too-long')
        self.assertEqual(self.code(self.cell_xml('', f'office:value-type="float" office:value="{long_value}"')), 'cell-text-too-long')
        ok = 'z' * ods.MAX_TEXT
        self.assertEqual(ods.read_ods(self.cell_xml('', f'office:value-type="string" office:string-value="{ok}"'))['S'], [[ok]])

    def test_the_whole_file_has_a_total_text_cap(self) -> None:
        # many cells that are each under the per-cell cap still add up (review D2): about 100 bytes of XML stores 2,000 characters
        old = ods.MAX_TOTAL_TEXT
        ods.MAX_TOTAL_TEXT = 10_000
        try:
            cells = [['x' * 1999] for _ in range(6)]                                   # 11,994 characters in all
            self.assertEqual(self.code(make_ods({'S': cells})), 'file-text-too-long')
            self.assertEqual(self.code(make_ods({'S': [[Rep('y' * 1000, 12)]]})), 'file-text-too-long')   # a repeated cell counts every copy
            self.assertEqual(ods.read_ods(make_ods({'S': cells[:4]}))['S'], cells[:4])   # 7,996: under the total, still read
        finally:
            ods.MAX_TOTAL_TEXT = old
        self.assertGreaterEqual(ods.MAX_TOTAL_TEXT, 10 * 4_300_000)                    # the real DRT122F holds about 4.3 million characters

    def test_the_xml_cap_is_a_margin_over_the_real_files_not_a_free_for_all(self) -> None:
        self.assertLessEqual(ods.MAX_XML_BYTES, 150_000_000)                      # the real DRT122F content.xml is 65 MB

    def test_cell_text_cap(self) -> None:
        self.assertEqual(self.code(make_ods({'S': [['x' * (ods.MAX_TEXT + 10)]]})), 'cell-text-too-long')


if __name__ == '__main__':
    unittest.main()
