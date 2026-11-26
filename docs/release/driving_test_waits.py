"""GB driving-test waits: read the DVSA ODS tables, normalise them, derive ranks and changes. No network, no file writes.

Pure functions only (bytes in, rows out), so the whole of it runs on SYNTHETIC files in the tests. The page, the
dataset files and the publish step are in driving_test_waits_site.py; the download is in fetch_driving_test_waits.py.

Source (Open Government Licence v3.0, Crown copyright; the licence was read on the gov.uk page on 26 Nov 2026):
https://www.gov.uk/government/statistical-data-sets/driving-test-and-theory-test-data-cars  (DVSA, ODS files only)
    DRT122F  waits and availability by test centre, Jan 2019 to date, monthly      (this module: parse_centres)
    DRT121G  the same by country and region, monthly                               (parse_regions)
    DRT121A  national tests conducted and passed, quarterly                        (parse_national)
    DRT121B  quarterly, 62 KB: its layout is not known, it is not read in v1       (TODO)

================================  ASSUMED_LAYOUT: NOTHING BELOW IS CONFIRMED  ================================
No real DVSA ODS file has been opened by anyone yet (the first download needs Russell's yes). Every sheet, header and
cell-format rule below comes from the feasibility note (Orchestrator drafts/feasibility-driving-test-waits-26-nov.md,
from the 16 Oct column list and the 9 Sep 2026 change note) and is an ASSUMPTION, marked ASSUMED. The build fails closed
on every one of them (exit 3, nothing written) and `driving_test_waits_site.py --describe` prints the real sheet names
and header rows (no data rows) so the constants can be set from facts at the first real file:
  A1 the data sheet is the only sheet with a header row, in its first 40 rows, equal to the header list below;
  A2 header texts (normalised: lower case, one space, no [note] marks, dashes as -) are exactly CENTRE_HEADERS /
     REGION_HEADERS / NATIONAL_HEADERS below (the wording is a guess; the order and the fourteen columns are from the note);
  A3 Month is an ODS date, 'YYYY-MM', 'Mon YYYY', 'Month YYYY' or 'Mon-YY' (only the year and month are used);
  A4 shares are plain numbers 0 to 100 (not fractions), and each row's four shares add to 100 +- 1 when all are present;
  A5 a cell is a number (thousands commas allowed) or exactly one of the codes [x] [n] [r] [z] [rv], blank = no value;
  A6 a closed centre has the prefix '[z]' on its name; data from PROVISIONAL_FROM on is provisional;
  A7 no total or subtotal row sits among the centre rows (a blank centre name stops the build);
  A8 after the first blank row only note lines (one non-empty cell at most) may follow.
==================================================================================================================
Rules kept from the feasibility note: codes are kept (never imputed) in `suppressed`; a closed centre is flagged; a
stable centre key from region plus name; provisional months are marked; arithmetic only on DVSA's own figures.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

import dvsa_ods

CODES = ('x', 'n', 'r', 'z', 'rv')                     # ASSUMED set (feasibility note); any other bracket code is refused
PROVISIONAL_FROM = '2025-04'                           # ASSUMED (A6): DVSA marks data since April 2025 provisional
HEADER_SEARCH_ROWS = 40
COUNTRIES = ('England', 'Scotland', 'Wales')
REGION_COUNTRIES = COUNTRIES + ('Great Britain',)      # ASSUMED: DRT121G may carry a whole-GB row
FIRST_MONTH = '2019-01'
MAX_WEEKS = Decimal(200)
MAX_SLOTS = 1_000_000

# (field, assumed normalised header text). The order is from the note; the wording is a guess (A2).
_NUMERIC = (
    ('slotsOvertime', 'test slots provided through overtime'),
    ('weeksTo10pcAvailability', 'weeks to 10%+ weekly appointment availability'),
    ('medianWaitWeeks', 'median wait (weeks)'),
    ('shareWithin7Weeks', '% taken within 7 weeks'),
    ('share7to14', '% taken within 7-14 weeks'),
    ('share14to21', '% taken within 14-21 weeks'),
    ('shareOver21', '% taken over 21 weeks'),
    ('slotsInWindow', 'total standard tests made available within the booking window (24 weeks)'),
    ('slotsBooked', 'booked'),
    ('slotsAvailable', 'still available'),
)
CENTRE_HEADERS = (('country', 'country'), ('region', 'region'), ('centre', 'driving test centre'), ('month', 'month')) + _NUMERIC
REGION_HEADERS = (('country', 'country'), ('region', 'region'), ('month', 'month')) + _NUMERIC
NATIONAL_HEADERS = (('period', 'quarter'), ('testsConducted', 'tests conducted'), ('testsPassed', 'tests passed'),
                    ('passRatePct', 'pass rate (%)'))
SHARES = ('shareWithin7Weeks', 'share7to14', 'share14to21', 'shareOver21')
COUNTS = ('slotsOvertime', 'slotsInWindow', 'slotsBooked', 'slotsAvailable')
WEEKS = ('weeksTo10pcAvailability', 'medianWaitWeeks')
NUMERIC_FIELDS = tuple(f for f, _ in _NUMERIC)

CODE_CELL_RE = re.compile(r'\[([a-z]{1,3})\]')
NUMBER_RE = re.compile(r'-?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?')
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


def parse_month(text: str) -> str:
    """ASSUMED formats (A3). Returns 'YYYY-MM' or raises LayoutError."""
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


_FULL_MONTHS = {'january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october',
                'november', 'december', 'sept'}


def parse_cell(text: str, *, where: str) -> tuple[Decimal | None, str | None]:
    """(number, None), (None, code) or (None, None) for a blank (A5). Anything else raises LayoutError."""
    cleaned = text.strip()
    if not cleaned:
        return None, None
    code = CODE_CELL_RE.fullmatch(cleaned)
    if code:
        if code[1] not in CODES:
            raise LayoutError(f'{where}: an unknown redaction code')
        return None, code[1]
    if NUMBER_RE.fullmatch(cleaned):
        try:
            return Decimal(cleaned.replace(',', '')), None
        except InvalidOperation:
            raise LayoutError(f'{where}: a number cell is not a number') from None
    raise LayoutError(f'{where}: a cell is neither a number nor a known code')


def _number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


# ------------------------------------------------------------------------------ finding the table

def locate_table(sheets: dict[str, list[list[str]]], headers: tuple[tuple[str, str], ...], table: str) -> list[list[str]]:
    """The data rows (header row excluded) of the one sheet that has the header row (A1, A2, A7, A8)."""
    expected = [text for _, text in headers]
    found: list[tuple[str, int]] = []
    for name, rows in sheets.items():
        for index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
            if [normalise_header(c) for c in row] == expected:
                found.append((name, index))
                break
    if not found:
        raise LayoutError(f'{table}: no sheet has the expected header row (the layout changed, or it is not yet confirmed)')
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
            continue                                # a note line (A8)
        if len(row) > len(expected):
            raise LayoutError(f'{table}: row {offset} has more cells than the header')
        data.append(row + [''] * (len(expected) - len(row)))
    if not data:
        raise LayoutError(f'{table}: the table has a header and no rows')
    return data


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
    rank: int | None = None
    change3m: float | None = None
    change6m: float | None = None
    change12m: float | None = None


def _check_name(text: str, what: str, row: int) -> str:
    if not NAME_RE.fullmatch(text):
        raise LayoutError(f'row {row}: the {what} is empty or not a name')
    return text


def _parse_numeric(cells: dict[str, str], row: int) -> tuple[dict[str, int | float | None], dict[str, str]]:
    values: dict[str, int | float | None] = {}
    codes: dict[str, str] = {}
    exact: dict[str, Decimal | None] = {}
    for name in NUMERIC_FIELDS:
        number, code = parse_cell(cells[name], where=f'row {row} {name}')
        exact[name] = number
        values[name] = None if number is None else _number(number)
        if code:
            codes[name] = code
        if number is None:
            continue
        if number < 0:
            raise LayoutError(f'row {row} {name}: a negative figure')
        if name in SHARES and number > 100:
            raise LayoutError(f'row {row} {name}: a share above 100 (A4: shares are 0 to 100)')
        if name in WEEKS and number > MAX_WEEKS:
            raise LayoutError(f'row {row} {name}: a wait above {MAX_WEEKS} weeks')
        if name in COUNTS and number > MAX_SLOTS:
            raise LayoutError(f'row {row} {name}: a count above {MAX_SLOTS:,}')
        if name in COUNTS and number != number.to_integral_value():
            raise LayoutError(f'row {row} {name}: a count that is not whole')
    present = [exact[n] for n in SHARES]
    if all(v is not None for v in present) and abs(sum(present) - 100) > 1:       # A4
        raise LayoutError(f'row {row}: the four shares do not add to 100 (percent or fraction?)')
    return values, codes


def parse_centres(sheets: dict[str, list[list[str]]]) -> list[WaitRow]:
    """DRT122F -> one WaitRow per centre-month, with the layout checks A1 to A8 and the data checks above."""
    data = locate_table(sheets, CENTRE_HEADERS, 'DRT122F')
    names = [f for f, _ in CENTRE_HEADERS]
    rows: list[WaitRow] = []
    seen: set[tuple[str, str]] = set()
    for index, cells in enumerate(data, start=1):
        record = dict(zip(names, cells))
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
        values, codes = _parse_numeric(record, index)
        rows.append(WaitRow(month, country, region, key, centre, 'closed' if closed else 'open', values, codes,
                            provisional=month >= PROVISIONAL_FROM))
    return rows


def parse_regions(sheets: dict[str, list[list[str]]]) -> list[WaitRow]:
    """DRT121G -> one WaitRow per region-month (no centre)."""
    data = locate_table(sheets, REGION_HEADERS, 'DRT121G')
    names = [f for f, _ in REGION_HEADERS]
    rows: list[WaitRow] = []
    seen: set[tuple[str, str, str]] = set()
    for index, cells in enumerate(data, start=1):
        record = dict(zip(names, cells))
        if record['country'] not in REGION_COUNTRIES:
            raise LayoutError(f'row {index}: the country is not England, Scotland, Wales or Great Britain')
        region = _check_name(record['region'], 'region', index)
        month = parse_month(record['month'])
        if (record['country'], region, month) in seen:
            raise LayoutError(f'row {index}: a region appears twice in {month}')
        seen.add((record['country'], region, month))
        values, codes = _parse_numeric(record, index)
        rows.append(WaitRow(month, record['country'], region, None, None, None, values, codes,
                            provisional=month >= PROVISIONAL_FROM))
    return rows


def parse_national(sheets: dict[str, list[list[str]]]) -> list[dict[str, Any]]:
    """DRT121A -> one dict per period. ASSUMED columns (see NATIONAL_HEADERS); the period text is kept as DVSA wrote it."""
    data = locate_table(sheets, NATIONAL_HEADERS, 'DRT121A')
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, (period, conducted, passed, rate) in enumerate((r[:4] for r in data), start=1):
        if not period or len(period) > 40 or period in seen or any(ord(c) < 32 for c in period):
            raise LayoutError(f'row {index}: the period is empty, long or repeated')
        seen.add(period)
        row: dict[str, Any] = {'period': period, 'suppressed': {}}
        for name, text in (('testsConducted', conducted), ('testsPassed', passed), ('passRatePct', rate)):
            number, code = parse_cell(text, where=f'row {index} {name}')
            row[name] = None if number is None else _number(number)
            if code:
                row['suppressed'][name] = code
            if number is not None and (number < 0 or (name == 'passRatePct' and number > 100)):
                raise LayoutError(f'row {index} {name}: out of range')
        out.append(row)
    return out


def read_table(data: bytes, parser: Any) -> list[Any]:
    """bytes of an .ods -> rows, with an unreadable or hostile file reported as a LayoutError (one exit path)."""
    try:
        sheets = dvsa_ods.read_ods(data)
    except dvsa_ods.OdsError as error:
        raise LayoutError(f'the file cannot be read safely ({error.code})') from None
    return parser(sheets)


# ------------------------------------------------------------------------------ derived columns

def derive(rows: list[WaitRow]) -> None:
    """rank (that month, 1 = longest median wait, ties share the lowest rank, open centres with a value only) and the 3, 6
    and 12-month changes in weeks (the same centre; None when either month is missing, never interpolated). Works in
    place. Pure arithmetic on DVSA's figures."""
    by_month: dict[str, list[WaitRow]] = {}
    lookup: dict[tuple[str, str], Decimal] = {}
    for row in rows:
        median = row.values.get('medianWaitWeeks')
        if row.centreKey is not None and median is not None:
            lookup[(row.centreKey, row.month)] = Decimal(str(median))
            if row.centreStatus == 'open':
                by_month.setdefault(row.month, []).append(row)
    for members in by_month.values():
        ordered = sorted(members, key=lambda r: -Decimal(str(r.values['medianWaitWeeks'])))
        first_at: dict[Any, int] = {}
        for position, row in enumerate(ordered, start=1):
            row.rank = first_at.setdefault(row.values['medianWaitWeeks'], position)
    for row in rows:
        if row.centreKey is None or (row.centreKey, row.month) not in lookup:
            continue
        now = lookup[(row.centreKey, row.month)]
        for attr, months in (('change3m', 3), ('change6m', 6), ('change12m', 12)):
            before = lookup.get((row.centreKey, month_minus(row.month, months)))
            if before is not None:
                setattr(row, attr, float(now - before))
