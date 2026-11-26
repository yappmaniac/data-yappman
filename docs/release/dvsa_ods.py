"""A bounded, standard-library reader for OpenDocument spreadsheets (.ods), for the DVSA driving-test files.

No network, no third-party package. Used by docs/release/driving_test_waits.py. It reads ONLY `content.xml` of the
zip and returns each sheet as a list of rows of plain text cells:

    sheets = read_ods(data)        # {'sheet name': [['cell', 'cell', ...], ...], ...}

Safety (a file from the web is untrusted data; the DVSA files are public but the monthly re-fetch is unattended):
- the input must be a zip with exactly one `content.xml` and no encrypted member; the member's declared and its
  actual uncompressed size are both capped (a zip bomb stops at MAX_XML_BYTES, whatever the header says), and so is the
  compression ratio;
- the XML is parsed with expat directly; any DOCTYPE or ENTITY declaration is refused (no entity expansion, no external
  entity, no DTD), and the parser never touches the network or the disk;
- row, column and cell counts are capped; an empty repeated cell or row is never expanded, and trailing empty cells
  and rows are dropped, so a sheet that claims a million blank rows costs nothing;
- every refusal is an OdsError carrying a short code (the build maps it to exit 3, nothing written).

Cell text: a number cell gives its `office:value` as written in the file (so 1234 not "1,234"), a date cell its
`office:date-value`, a boolean its `office:boolean-value`, everything else the text:p text (several paragraphs are
joined with a newline). Covered cells (merged areas) read as empty.
"""

from __future__ import annotations

import io
import zipfile
from typing import Any
from xml.parsers import expat

MAX_ZIP_BYTES = 40_000_000          # the DVSA files are 0.01 to 9 MB; far more than this is not one of them
MAX_XML_BYTES = 150_000_000         # content.xml, uncompressed (the real DRT122F is 65 MB; a hostile file stops here)
MAX_RATIO = 400                     # uncompressed / compressed; XML of repeated rows compresses well, a bomb far more
MAX_SHEETS = 40
MAX_ROWS = 250_000                  # per sheet, after trimming (DRT122F is about 33,000 rows)
MAX_COLS = 80
MAX_CELLS = 6_000_000               # per file, non-empty plus the empty cells inside a row's width
MAX_TEXT = 2_000                    # one cell's text, counted over EVERY piece: characters, spaces, tabs, line breaks, paragraphs, attributes
MAX_PARAGRAPHS = 50                 # text:p elements in one cell
CHUNK = 1 << 16

NS_OFFICE = 'urn:oasis:names:tc:opendocument:xmlns:office:1.0'
NS_TABLE = 'urn:oasis:names:tc:opendocument:xmlns:table:1.0'
NS_TEXT = 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'
SEP = ' '


def _q(ns: str, local: str) -> str:
    return f'{ns}{SEP}{local}'


T_TABLE, T_ROW, T_CELL, T_COVERED = (_q(NS_TABLE, n) for n in ('table', 'table-row', 'table-cell', 'covered-table-cell'))
T_HEADER_ROWS, T_ROW_GROUP, T_ROWS = (_q(NS_TABLE, n) for n in ('table-header-rows', 'table-row-group', 'table-rows'))
T_P, T_SPAN, T_TAB, T_LB, T_S = (_q(NS_TEXT, n) for n in ('p', 'span', 'tab', 'line-break', 's'))
A_NAME, A_ROW_REP, A_COL_REP = (_q(NS_TABLE, n) for n in ('name', 'number-rows-repeated', 'number-columns-repeated'))
A_TYPE, A_VALUE, A_DATE, A_BOOL = (_q(NS_OFFICE, n) for n in ('value-type', 'value', 'date-value', 'boolean-value'))
A_STRING = _q(NS_OFFICE, 'string-value')
OFFICE_BODY = _q(NS_OFFICE, 'document-content')


class OdsError(Exception):
    """The file is not a safe, readable ODS. `code` is short and fixed (never the file's text)."""

    def __init__(self, code: str, detail: str = '') -> None:
        super().__init__(code)
        self.code, self.detail = code, detail


def _open_content(data: bytes) -> bytes:
    """content.xml's bytes, with the size and ratio limits enforced as the bytes are read."""
    if len(data) > MAX_ZIP_BYTES:
        raise OdsError('zip-too-large')
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, OSError):
        raise OdsError('not-a-zip') from None
    with archive:
        members = [i for i in archive.infolist() if i.filename == 'content.xml']
        if len(members) != 1:
            raise OdsError('content-xml-not-single')
        info = members[0]
        if info.flag_bits & 0x1:
            raise OdsError('encrypted')
        if info.file_size > MAX_XML_BYTES or (info.compress_size and info.file_size / info.compress_size > MAX_RATIO):
            raise OdsError('content-too-large')
        out = bytearray()
        try:
            with archive.open(info) as stream:
                while True:
                    block = stream.read(CHUNK)
                    if not block:
                        break
                    out += block
                    if len(out) > MAX_XML_BYTES:
                        raise OdsError('content-too-large')
        except (zipfile.BadZipFile, OSError, RuntimeError, EOFError, ValueError):
            raise OdsError('zip-unreadable') from None
        if len(out) != info.file_size:
            raise OdsError('size-mismatch')
        return bytes(out)


class _Reader:
    """Streams expat events into {sheet name: rows}. One instance per file."""

    def __init__(self) -> None:
        self.sheets: dict[str, list[list[str]]] = {}
        self._rows: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._row_repeat = 1
        self._gap = 0                       # empty cells seen since the last non-empty one in this row
        self._cell: dict[str, Any] | None = None
        self._p_depth = 0
        self._paras: list[str] = []
        self._buf: list[str] = []
        self._cell_len = 0                  # characters held so far in the current cell, all pieces
        self._cells = 0
        self._depth = 0
        self._root_seen = False

    # --- expat handlers -------------------------------------------------------------------------------------------
    def start(self, name: str, attrs: dict[str, str]) -> None:
        self._depth += 1
        if self._depth == 1:
            if name != OFFICE_BODY:
                raise OdsError('not-an-ods-content-file')
            self._root_seen = True
            return
        if name == T_TABLE and self._rows is None:
            title = attrs.get(A_NAME)
            if title is None or title in self.sheets or len(self.sheets) >= MAX_SHEETS:
                raise OdsError('sheet-name-missing-repeated-or-too-many')
            self._rows = self.sheets.setdefault(title, [])
        elif name == T_ROW and self._rows is not None and self._row is None:
            self._row, self._gap = [], 0
            self._row_repeat = self._count(attrs.get(A_ROW_REP))
        elif name in (T_CELL, T_COVERED) and self._row is not None and self._cell is None:
            repeat = self._count(attrs.get(A_COL_REP))
            kind = attrs.get(A_TYPE) if name == T_CELL else None
            if kind in ('float', 'percentage', 'currency'):
                direct: str | None = attrs.get(A_VALUE)
            elif kind == 'date':
                direct = attrs.get(A_DATE)
            elif kind == 'boolean':
                direct = attrs.get(A_BOOL)
            else:
                direct = attrs.get(A_STRING) if kind == 'string' else None
            if direct is not None and len(direct) > MAX_TEXT:
                raise OdsError('cell-text-too-long')
            self._cell = {'repeat': repeat, 'direct': direct}
            self._paras, self._buf, self._p_depth, self._cell_len = [], [], 0, 0
        elif self._cell is not None:
            if name == T_P and self._p_depth == 0:
                if len(self._paras) >= MAX_PARAGRAPHS:
                    raise OdsError('cell-text-too-long')
                self._add(1 if self._paras else 0)           # the newline that will join it to the paragraph before
                self._p_depth = 1
                self._buf = []
            elif self._p_depth and name == T_TAB:
                self._add(1)
                self._buf.append('\t')
            elif self._p_depth and name == T_LB:
                self._add(1)
                self._buf.append('\n')
            elif self._p_depth and name == T_S:
                spaces = self._count(attrs.get(_q(NS_TEXT, 'c')))
                self._add(spaces)                              # checked BEFORE the string is built
                self._buf.append(' ' * spaces)
            elif self._p_depth:
                self._p_depth += 1          # a span or similar inside the paragraph

    def end(self, name: str) -> None:
        self._depth -= 1
        if self._cell is not None:
            if name == T_P and self._p_depth == 1:
                self._paras.append(''.join(self._buf))
                self._p_depth = 0
            elif self._p_depth > 1:
                self._p_depth -= 1
            if name in (T_CELL, T_COVERED):
                self._finish_cell()
            return
        if name == T_ROW and self._row is not None:
            self._finish_row()
        elif name == T_TABLE and self._row is None and self._rows is not None:
            while self._rows and not any(self._rows[-1]):
                self._rows.pop()            # trailing empty rows
            self._rows = None

    def chars(self, text: str) -> None:
        if self._cell is not None and self._p_depth:
            self._add(len(text))
            self._buf.append(text)

    def _add(self, count: int) -> None:
        """Count text added to the current cell, whatever the element it came from; refuse past MAX_TEXT."""
        self._cell_len += count
        if self._cell_len > MAX_TEXT:
            raise OdsError('cell-text-too-long')

    def refuse_declaration(self, *args: Any) -> None:
        raise OdsError('doctype-or-entity-refused')

    # --- helpers --------------------------------------------------------------------------------------------------
    @staticmethod
    def _count(raw: str | None) -> int:
        if raw is None:
            return 1
        if not raw.isascii() or not raw.isdigit() or not 1 <= int(raw) <= 10_000_000:
            raise OdsError('bad-repeat-count')
        return int(raw)

    def _finish_cell(self) -> None:
        cell, self._cell = self._cell, None
        assert cell is not None and self._row is not None
        text = cell['direct'] if cell['direct'] is not None else '\n'.join(self._paras)
        text = text.strip() if text is not None else ''
        if len(text) > MAX_TEXT:                              # the final text, whatever built it
            raise OdsError('cell-text-too-long')
        repeat = cell['repeat']
        if not text:
            self._gap += repeat             # remembered as a count; written only if a non-empty cell follows
            return
        if repeat > MAX_COLS or len(self._row) + self._gap + repeat > MAX_COLS:
            raise OdsError('too-many-columns' if repeat <= MAX_COLS else 'non-empty-cell-repeated-too-often')
        self._row.extend([''] * self._gap)
        self._gap = 0
        self._row.extend([text] * repeat)

    def _finish_row(self) -> None:
        row, self._row = self._row, None
        assert row is not None and self._rows is not None
        while row and not row[-1]:
            row.pop()
        repeat = self._row_repeat
        if not row:
            # an empty row: kept once if it is not a huge filler (blank lines inside the data are real rows)
            repeat = min(repeat, 1) if repeat < 1000 else 0
        else:
            if repeat > 1000:
                raise OdsError('non-empty-row-repeated-too-often')
        for _ in range(repeat):
            self._cells += len(row)
            if self._cells > MAX_CELLS or len(self._rows) >= MAX_ROWS:
                raise OdsError('too-many-cells-or-rows')
            self._rows.append(list(row))


def read_ods(data: bytes) -> dict[str, list[list[str]]]:
    """Every sheet of the file as rows of text cells, or an OdsError."""
    xml = _open_content(data)
    reader = _Reader()
    parser = expat.ParserCreate(namespace_separator=SEP)
    parser.buffer_text = False
    parser.ordered_attributes = False
    parser.StartElementHandler = reader.start
    parser.EndElementHandler = reader.end
    parser.CharacterDataHandler = reader.chars
    parser.StartDoctypeDeclHandler = reader.refuse_declaration
    parser.EntityDeclHandler = reader.refuse_declaration
    parser.ExternalEntityRefHandler = reader.refuse_declaration
    parser.NotationDeclHandler = reader.refuse_declaration
    parser.SkippedEntityHandler = reader.refuse_declaration
    try:
        parser.Parse(xml, True)
    except expat.ExpatError:
        raise OdsError('xml-not-well-formed') from None
    except RecursionError:
        raise OdsError('xml-too-deep') from None
    if not reader._root_seen or not reader.sheets:
        raise OdsError('no-sheets')
    return reader.sheets
