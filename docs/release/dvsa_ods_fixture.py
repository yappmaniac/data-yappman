"""Builds SYNTHETIC .ods files for the tests of dvsa_ods.py and driving_test_waits.py. Invented numbers only.

No real DVSA file is read or copied here. The sheet and column layout the tests use is an ASSUMPTION taken from the
feasibility note (Orchestrator drafts/feasibility-driving-test-waits-26-nov.md) and is marked in
driving_test_waits.py (ASSUMED_LAYOUT); it must be confirmed against the first real file.

    make_ods({'Sheet': [['a', 1, 2.5, None], ...]})  ->  bytes of a valid .ods (a zip with mimetype + content.xml)

Cell values: str (string cell), int/float (float cell, shown with thousands commas if shown=True in Num), None (an
empty cell), Date('2019-01-01'), Num(1234, shown='1,234'), Rep(cell, n) (number-columns-repeated), and in the row
list a RepRow(row, n) (number-rows-repeated).
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from typing import Any
from xml.sax.saxutils import escape, quoteattr

NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
      'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
      'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"')


@dataclass(frozen=True)
class Date:
    iso: str


@dataclass(frozen=True)
class Num:
    value: float
    shown: str | None = None      # the formatted text the spreadsheet shows, e.g. '1,234'


@dataclass(frozen=True)
class Rep:
    cell: Any
    times: int


@dataclass(frozen=True)
class RepRow:
    row: list[Any]
    times: int


def _cell(value: Any) -> str:
    repeat = ''
    if isinstance(value, Rep):
        repeat, value = f' table:number-columns-repeated="{value.times}"', value.cell
    if value is None:
        return f'<table:table-cell{repeat}/>'
    if isinstance(value, Date):
        return (f'<table:table-cell office:value-type="date" office:date-value={quoteattr(value.iso)}{repeat}>'
                f'<text:p>{escape(value.iso)}</text:p></table:table-cell>')
    if isinstance(value, Num):
        shown = value.shown if value.shown is not None else str(value.value)
        return (f'<table:table-cell office:value-type="float" office:value="{value.value}"{repeat}>'
                f'<text:p>{escape(shown)}</text:p></table:table-cell>')
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (f'<table:table-cell office:value-type="float" office:value="{value}"{repeat}>'
                f'<text:p>{value}</text:p></table:table-cell>')
    return (f'<table:table-cell office:value-type="string"{repeat}><text:p>{escape(str(value))}</text:p>'
            f'</table:table-cell>')


def _row(row: Any) -> str:
    repeat = ''
    if isinstance(row, RepRow):
        repeat, row = f' table:number-rows-repeated="{row.times}"', row.row
    return f'<table:table-row{repeat}>' + ''.join(_cell(c) for c in row) + '</table:table-row>'


def content_xml(sheets: dict[str, list[Any]], *, prefix: str = '') -> bytes:
    """The content.xml text; `prefix` goes before the root element (for a DOCTYPE test)."""
    body = ''.join(f'<table:table table:name={quoteattr(name)}>' + ''.join(_row(r) for r in rows) + '</table:table>'
                   for name, rows in sheets.items())
    return (f'<?xml version="1.0" encoding="UTF-8"?>{prefix}<office:document-content {NS}>'
            f'<office:body><office:spreadsheet>{body}</office:spreadsheet></office:body></office:document-content>'
            ).encode('utf-8')


def make_ods(sheets: dict[str, list[Any]], *, prefix: str = '', extra_members: dict[str, bytes] | None = None,
             raw_content: bytes | None = None, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    """A valid .ods as bytes. `raw_content` replaces content.xml (for broken or hostile XML)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression) as archive:
        archive.writestr('mimetype', 'application/vnd.oasis.opendocument.spreadsheet', compress_type=zipfile.ZIP_STORED)
        archive.writestr('content.xml', raw_content if raw_content is not None else content_xml(sheets, prefix=prefix))
        for name, data in (extra_members or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()
