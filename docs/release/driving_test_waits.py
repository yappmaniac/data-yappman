"""GB driving-test waits: read the DVSA ODS tables, normalise them, derive ranks and changes. No network, no file writes.

Pure functions only (bytes in, rows out), so the whole of it runs on SYNTHETIC files in the tests. The page, the
dataset files and the publish step are in driving_test_waits_site.py; the download is in fetch_driving_test_waits.py.

Source (Open Government Licence v3.0, Crown copyright; the licence was read on the gov.uk page on 26 Nov 2026):
https://www.gov.uk/government/statistical-data-sets/driving-test-and-theory-test-data-cars  (DVSA, ODS files only)
    DRT122F  waits and availability by test centre, Jan 2019 to date, monthly      (parse_centres)
    DRT121G  tests, pass rates and waits by country and region, monthly            (parse_regions)
    DRT121A  tests conducted and passed by financial quarter and year, GB          (parse_national)
    DRT121B  the same by month and gender: fetched, not read in v1                 (TODO)

LAYOUT: CONFIRMED against the real 11 Nov 2026 release (files updated 13 Nov; the Orchestrator's fetch of 26 Nov read at
18:55 UTC; DRT122F 4,124,318 bytes, DRT121G 273,948, DRT121A 12,936, DRT121B 61,156). What the real files show, and what
the build relies on (a change in any of it is exit 3, nothing written):
  - each workbook has Cover_sheet (or Cover_Sheet), Notes and one data sheet named like the table; the data sheet has
    title and shorthand lines, then the header row (row 4 of DRT122F and DRT121G, row 6 of DRT121A), then the data, with
    no blank row. The cover sheet reads "Last updated: 11 November 2026" (DRT122F) and "3 September 2026" (DRT121A, a
    quarterly table, next in December 2026);
  - DRT122F: 16 columns (Country, Region, Driving test centre, Month, then 10 figures, then a Notes column that holds
    only a [z] marker, which is ignored), 30,449 rows, 94 months (2019-01 to 2026-10), 274 to 342 centres a month,
    Country in England/Scotland/Wales, 11 regions (Scotland and Wales are regions of their own), no repeated
    (region, centre, month);
  - the Month cell is an ISO date-time text ('2019-01-01T00:00:00'), the first of the month;
  - shorthand, as DVSA defines it on the sheet: [n] no tests conducted, [r] redacted (10 or fewer), [x] not available,
    [z] not applicable, [rv] revised (DRT121A and B add [c] confidential); a centre name prefixed [z] is closed (621 rows);
  - cells are numbers as text ('1944', '6.8571428571428603', '8.5178875638841606E-1', '1,000': the newest month's counts
    carry thousands commas), codes in square brackets, one 'N/A' in the "still available (Percentage)" column (50 rows),
    and a few blank cells. Floating-point noise from the spreadsheet ('68.599999999999994') is rounded to 15 significant
    digits, which gives DVSA's intended figure (68.6) and changes nothing that was published;
  - the four shares add to 100 within 0.1 in every real row that has all four (percentages, not fractions); the build allows a
    difference of 1 before it stops;
  - "Data since April 2025 is provisional and will be refreshed on a quarterly basis" (note 1 of DRT122F and DRT121G);
  - the booking window is 24 weeks (18 weeks until May 2021) measured on the last Monday of each month (notes 10 to 12);
  - DRT121G: 18 columns, level 'Country' (Great Britain, England, Scotland, Wales) or 'Region' (the 9 English regions only;
    Scotland and Wales appear at Country level), 'Yorkshire and The Humber' also written 'Yorkshire and the Humber' (mapped to
    one name); the build also accepts a Region row named after a region of the centre table;
  - DRT121A: 'Date Interval' ('Financial Quarter' 77 rows, 'Financial Year' 20) and 'Date' text such as
    '2007 to 2008 Q1 April to June' or '2026 to 2027 (ytd)'.
Rules kept from the feasibility note: codes are kept (never imputed) in `suppressed`; a closed centre is flagged; a stable
centre key from region plus name; provisional months are marked; arithmetic only on DVSA's own figures.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import dvsa_ods

CODES = ('x', 'n', 'r', 'z', 'rv', 'c')       # DVSA's shorthand: not available, no tests, redacted (10 or fewer), not applicable, revised, confidential
NA_TEXT = 'N/A'                                # one column carries this text where there is no figure (50 rows on 26 Nov 2026)
PROVISIONAL_FROM = '2025-04'                   # note 1: "Data since April 2025 is provisional"
HEADER_SEARCH_ROWS = 40
COUNTRIES = ('England', 'Scotland', 'Wales')
COUNTRY_LEVEL_AREAS = ('Great Britain',) + COUNTRIES
LEVELS = ('Country', 'Region')
FIRST_MONTH = '2019-01'
MAX_WEEKS = Decimal(200)
MAX_SLOTS = 1_000_000
MAX_TESTS = 10_000_000
SIGNIFICANT_DIGITS = 15                        # spreadsheet noise ('68.599999999999994') is rounded away at the 16th digit

# (field, normalised header text as the real files write it, without [note n] marks).
_NUMERIC = (
    ('slotsOvertime', 'test slots provided through overtime'),
    ('weeksTo10pcAvailability', 'weeks to 10%+ weekly appointment availability'),
    ('medianWaitWeeks', 'average (median) waiting time between booking and taking the test (weeks)'),
    ('shareWithin7Weeks', 'tests taken within 7 weeks of booking (percentage)'),
    ('share7to14', 'tests taken in more than 7 and up to 14 weeks of booking (percentage)'),
    ('share14to21', 'tests taken in more than 14 and up to 21 weeks of booking (percentage)'),
    ('shareOver21', 'tests taken in more than 21 weeks of booking (percentage)'),
    ('slotsInWindow', 'total standard tests made available within the booking window'),
    ('slotsBooked', 'standard tests booked within the booking window'),
    ('slotsAvailable', 'standard tests still available to book within the booking window'),
    ('slotsAvailablePct', 'standard tests still available to book within the booking window (percentage)'),
)
_NOTES = ('notes', 'notes')                    # a footnote-marker column, ignored (holds [z] or [Z])
CENTRE_HEADERS = (('country', 'country'), ('region', 'region'), ('centre', 'driving test centre'),
                  ('month', 'month')) + _NUMERIC + (_NOTES,)
REGION_EXTRA = (('testsConducted', 'total tests conducted with outcome'), ('testsPassed', 'tests passed'),
                ('passRatePct', 'pass rate (percentage)'))
REGION_HEADERS = (('level', 'geographic level'), ('area', 'geographic area name'), ('month', 'month')) + REGION_EXTRA + _NUMERIC + (_NOTES,)
NATIONAL_HEADERS = (('interval', 'date interval'), ('period', 'date'), ('testsConducted', 'conducted'), ('testsPassed', 'passed'),
                    ('passRatePct', 'pass rate (percentage)'), _NOTES)
INTERVALS = ('Financial Quarter', 'Financial Year')
SHARES = ('shareWithin7Weeks', 'share7to14', 'share14to21', 'shareOver21')
PERCENTS = SHARES + ('slotsAvailablePct', 'passRatePct')
COUNTS = ('slotsOvertime', 'slotsInWindow', 'slotsBooked', 'slotsAvailable')
TEST_COUNTS = ('testsConducted', 'testsPassed')
WEEKS = ('weeksTo10pcAvailability', 'medianWaitWeeks')
NUMERIC_FIELDS = tuple(f for f, _ in _NUMERIC)
REGION_FIELDS = tuple(f for f, _ in REGION_EXTRA) + NUMERIC_FIELDS
# the one spelling difference in the real DRT121G: both are the same region
AREA_SPELLINGS = {'yorkshire and the humber': 'Yorkshire and The Humber'}

CODE_CELL_RE = re.compile(r'\[([A-Za-z]{1,3})\]')
NUMBER_RE = re.compile(r'-?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]{1,3})?')
NOTE_RE = re.compile(r'\s*\[[^\]]*\]')
NAME_RE = re.compile(r"[^\W\d_](?:[^\W\d_]|[ ,.'’&()/-]){0,99}")
MONTH_NAMES = {n: i for i, n in enumerate(
    ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'), start=1)}
CLOSED_PREFIX = '[z]'


class LayoutError(Exception):
    """The file does not have the layout this build expects (or a value breaks a rule). Short reason; the build exits 3."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ------------------------------------------------------------------------------ small helpers

def normalise_header(text: str) -> str:
    text = NOTE_RE.sub('', text).lower().replace('–', '-').replace('—', '-').replace('‐', '-')
    return ' '.join(text.split())


def month_minus(month: str, months: int) -> str:
    index = int(month[:4]) * 12 + int(month[5:7]) - 1 - months
    return f'{index // 12:04d}-{index % 12 + 1:02d}'


def slug(text: str) -> str:
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', text.lower())).strip('-')


_FULL_MONTHS = {'january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october',
                'november', 'december', 'sept'}


def parse_month(text: str) -> str:
    """'YYYY-MM-DD[THH:MM:SS]' (what the real files hold), 'YYYY-MM', 'Mon YYYY', 'Month YYYY' or 'Mon-YY'. Returns 'YYYY-MM'."""
    cleaned = text.strip()
    match = re.fullmatch(r'([0-9]{4})-([0-9]{2})(?:-[0-9]{2})?(?:T[0-9:.]+)?', cleaned)
    if match:
        year, month = int(match[1]), int(match[2])
    else:
        match = re.fullmatch(r'([A-Za-z]{3,9})[ -]([0-9]{4}|[0-9]{2})', cleaned)
        name = match[1][:3].lower() if match else ''
        if not match or name not in MONTH_NAMES or (len(match[1]) > 3 and match[1].lower() not in _FULL_MONTHS):
            raise LayoutError('a Month cell is not a date this build knows')
        year, month = int(match[2]) + (2000 if len(match[2]) == 2 else 0), MONTH_NAMES[name]
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        raise LayoutError('a Month cell is out of range')
    return f'{year:04d}-{month:02d}'


def parse_cell(text: str, *, where: str) -> tuple[Decimal | None, str | None]:
    """(number, None), (None, code) or (None, None) for a blank. 'N/A' is the code 'N/A'. Anything else raises LayoutError."""
    cleaned = text.strip()
    if not cleaned:
        return None, None
    if cleaned == NA_TEXT:
        return None, NA_TEXT
    code = CODE_CELL_RE.fullmatch(cleaned)
    if code:
        if code[1].lower() not in CODES:
            raise LayoutError(f'{where}: an unknown redaction code')
        return None, code[1].lower()
    if NUMBER_RE.fullmatch(cleaned):
        try:
            number = Decimal(cleaned.replace(',', ''))
            return Decimal(format(number, f'.{SIGNIFICANT_DIGITS}g')), None
        except (InvalidOperation, ValueError):
            raise LayoutError(f'{where}: a number cell is not a number') from None
    raise LayoutError(f'{where}: a cell is neither a number nor a known code')


def _number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


# ------------------------------------------------------------------------------ finding the table

def locate_table(sheets: dict[str, list[list[str]]], headers: tuple[tuple[str, str], ...], table: str) -> list[list[str]]:
    """The data rows (header row excluded) of the one sheet that has the header row. Short rows are padded to the
    header's width; a blank row ends the table and only note lines (one cell at most) may follow."""
    expected = [text for _, text in headers]
    found: list[tuple[str, int]] = []
    for name, rows in sheets.items():
        for index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
            if [normalise_header(c) for c in row] == expected:
                found.append((name, index))
                break
    if not found:
        raise LayoutError(f'{table}: no sheet has the expected header row (the layout changed)')
    if len(found) > 1:
        raise LayoutError(f'{table}: more than one sheet has the header row')
    name, start = found[0]
    body = sheets[name][start + 1:]
    data: list[list[str]] = []
    blank_seen = False
    for offset, row in enumerate(body, start=start + 2):
        filled = sum(1 for c in row if c)
        if not filled:
            blank_seen = True
            continue
        if blank_seen:
            if filled > 1:
                raise LayoutError(f'{table}: row {offset} holds data after a blank row')
            continue                                # a note line
        if len(row) > len(expected):
            raise LayoutError(f'{table}: row {offset} has more cells than the header')
        data.append(row + [''] * (len(expected) - len(row)))
    if not data:
        raise LayoutError(f'{table}: the table has a header and no rows')
    return data


def _check_marker(cell: str, row: int) -> None:
    """The Notes column holds a footnote marker such as [z] (or nothing); anything else means the layout moved."""
    if cell and not CODE_CELL_RE.fullmatch(cell.strip()):
        raise LayoutError(f'row {row}: the Notes column holds something other than a marker')


# ------------------------------------------------------------------------------ rows

@dataclass
class WaitRow:
    """One centre (or region) in one month. Figures are DVSA's own; None when blank or suppressed."""
    month: str
    country: str
    region: str
    centreKey: str | None
    centre: str | None
    centreStatus: str | None
    values: dict[str, int | float | None]
    suppressed: dict[str, str] = field(default_factory=dict)
    provisional: bool = False
    level: str | None = None                  # region rows only: 'Country' or 'Region'
    rank: int | None = None
    change3m: float | None = None
    change6m: float | None = None
    change12m: float | None = None

    @property
    def key(self) -> str:
        """The series a change is measured along: the centre, or the level, country and area for a region row."""
        return self.centreKey or f'{slug(self.level or "")}.{slug(self.country)}.{slug(self.region)}'


def _check_name(text: str, what: str, row: int) -> str:
    if not NAME_RE.fullmatch(text):
        raise LayoutError(f'row {row}: the {what} is empty or not a name')
    return text


def _parse_numeric(cells: dict[str, str], row: int, fields: tuple[str, ...]) -> tuple[dict[str, int | float | None], dict[str, str]]:
    values: dict[str, int | float | None] = {}
    codes: dict[str, str] = {}
    exact: dict[str, Decimal | None] = {}
    for name in fields:
        number, code = parse_cell(cells[name], where=f'row {row} {name}')
        exact[name] = number
        values[name] = None if number is None else _number(number)
        if code:
            codes[name] = code
        if number is None:
            continue
        if number < 0:
            raise LayoutError(f'row {row} {name}: a negative figure')
        if name in PERCENTS and number > 100:
            raise LayoutError(f'row {row} {name}: a percentage above 100')
        if name in WEEKS and number > MAX_WEEKS:
            raise LayoutError(f'row {row} {name}: a wait above {MAX_WEEKS} weeks')
        limit = MAX_SLOTS if name in COUNTS else MAX_TESTS if name in TEST_COUNTS else None
        if limit is not None and number > limit:
            raise LayoutError(f'row {row} {name}: a count above {limit:,}')
        if (name in COUNTS or name in TEST_COUNTS) and number != number.to_integral_value():
            raise LayoutError(f'row {row} {name}: a count that is not whole')
    present = [exact.get(n) for n in SHARES]
    if all(v is not None for v in present) and abs(sum(present) - 100) > 1:
        raise LayoutError(f'row {row}: the four shares do not add to 100 (percent or fraction?)')
    passed, conducted = values.get('testsPassed'), values.get('testsConducted')
    if passed is not None and conducted is not None and passed > conducted:
        raise LayoutError(f'row {row}: more tests passed than conducted')
    return values, codes


def parse_centres(sheets: dict[str, list[list[str]]]) -> list[WaitRow]:
    """DRT122F -> one WaitRow per centre-month."""
    data = locate_table(sheets, CENTRE_HEADERS, 'DRT122F')
    names = [f for f, _ in CENTRE_HEADERS]
    rows: list[WaitRow] = []
    seen: set[tuple[str, str]] = set()
    for index, cells in enumerate(data, start=1):
        record = dict(zip(names, cells))
        _check_marker(record['notes'], index)
        country = record['country']
        if country not in COUNTRIES:
            raise LayoutError(f'row {index}: the country is not one of England, Scotland, Wales')
        region = _check_name(record['region'], 'region', index)
        centre_text = record['centre']
        closed = centre_text.startswith(CLOSED_PREFIX)
        centre = _check_name(centre_text[len(CLOSED_PREFIX):].strip() if closed else centre_text, 'centre name', index)
        month = parse_month(record['month'])
        if month < FIRST_MONTH:
            raise LayoutError(f'row {index}: a month before {FIRST_MONTH}')
        key = f'{slug(region)}.{slug(centre)}'
        if not slug(region) or not slug(centre):
            raise LayoutError(f'row {index}: a region or centre with no letters')
        if (key, month) in seen:
            raise LayoutError(f'row {index}: the centre key {key} appears twice in {month}')
        seen.add((key, month))
        values, codes = _parse_numeric(record, index, NUMERIC_FIELDS)
        rows.append(WaitRow(month, country, region, key, centre, 'closed' if closed else 'open', values, codes,
                            provisional=month >= PROVISIONAL_FROM))
    return rows


def parse_regions(sheets: dict[str, list[list[str]]], region_country: dict[str, str]) -> list[WaitRow]:
    """DRT121G -> one WaitRow per area-month. `region_country` maps each region name (from DRT122F) to its country, so a
    region row can carry its country and an unknown region is refused."""
    data = locate_table(sheets, REGION_HEADERS, 'DRT121G')
    names = [f for f, _ in REGION_HEADERS]
    canonical = {r.lower(): r for r in region_country} | AREA_SPELLINGS
    rows: list[WaitRow] = []
    seen: set[tuple[str, str, str]] = set()
    for index, cells in enumerate(data, start=1):
        record = dict(zip(names, cells))
        _check_marker(record['notes'], index)
        level, area = record['level'], record['area']
        if level not in LEVELS:
            raise LayoutError(f'row {index}: the geographic level is not Country or Region')
        if level == 'Country':
            if area not in COUNTRY_LEVEL_AREAS:
                raise LayoutError(f'row {index}: a country-level area that is not Great Britain, England, Scotland or Wales')
            country = area
        else:
            area = canonical.get(area.lower(), area)
            if area not in region_country:
                raise LayoutError(f'row {index}: a region that is not a region of the centre table')
            country = region_country[area]
        month = parse_month(record['month'])
        if (level, area, month) in seen:
            raise LayoutError(f'row {index}: an area appears twice in {month}')
        seen.add((level, area, month))
        values, codes = _parse_numeric(record, index, REGION_FIELDS)
        rows.append(WaitRow(month, country, area, None, None, None, values, codes, provisional=month >= PROVISIONAL_FROM, level=level))
    return rows


def parse_national(sheets: dict[str, list[list[str]]]) -> list[dict[str, Any]]:
    """DRT121A -> one dict per financial quarter or year; the period text is kept as DVSA wrote it."""
    data = locate_table(sheets, NATIONAL_HEADERS, 'DRT121A')
    names = [f for f, _ in NATIONAL_HEADERS]
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, cells in enumerate(data, start=1):
        record = dict(zip(names, cells))
        _check_marker(record['notes'], index)
        interval, period = record['interval'], record['period']
        if interval not in INTERVALS:
            raise LayoutError(f'row {index}: the date interval is not Financial Quarter or Financial Year')
        if not period or len(period) > 60 or (interval, period) in seen or any(ord(c) < 32 for c in period):
            raise LayoutError(f'row {index}: the period is empty, long or repeated')
        seen.add((interval, period))
        values, codes = _parse_numeric(record, index, ('testsConducted', 'testsPassed', 'passRatePct'))
        out.append({'interval': interval, 'period': period, **values, 'suppressed': codes})
    return out


def read_table(data: bytes, parser: Any, *args: Any) -> list[Any]:
    """bytes of an .ods -> rows, with an unreadable or hostile file reported as a LayoutError (one exit path)."""
    try:
        sheets = dvsa_ods.read_ods(data)
    except dvsa_ods.OdsError as error:
        raise LayoutError(f'the file cannot be read safely ({error.code})') from None
    return parser(sheets, *args)


# ------------------------------------------------------------------------------ derived columns

def derive(rows: list[WaitRow]) -> None:
    """rank (that month, 1 = longest median wait, ties share the lowest rank, open centres with a value only) and the 3, 6
    and 12-month changes in weeks (the same centre; None when either month is missing, never interpolated). Works in
    place. Pure arithmetic on DVSA's figures."""
    by_month: dict[str, list[WaitRow]] = {}
    lookup: dict[tuple[str, str], Decimal] = {}
    for row in rows:
        median = row.values.get('medianWaitWeeks')
        if median is None:
            continue
        lookup[(row.key, row.month)] = Decimal(str(median))
        if row.centreKey is not None and row.centreStatus == 'open':
            by_month.setdefault(row.month, []).append(row)
    for members in by_month.values():
        ordered = sorted(members, key=lambda r: -Decimal(str(r.values['medianWaitWeeks'])))
        first_at: dict[Any, int] = {}
        for position, row in enumerate(ordered, start=1):
            row.rank = first_at.setdefault(row.values['medianWaitWeeks'], position)
    for row in rows:
        if (row.key, row.month) not in lookup:
            continue
        now = lookup[(row.key, row.month)]
        for attr, months in (('change3m', 3), ('change6m', 6), ('change12m', 12)):
            before = lookup.get((row.key, month_minus(row.month, months)))
            if before is not None:
                setattr(row, attr, float((now - before).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)))
