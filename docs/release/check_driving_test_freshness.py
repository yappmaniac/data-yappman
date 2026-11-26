"""Driving-test waits: is what is published still fresh, and does the page match the files? No network, no write.

    python -I -B docs/release/check_driving_test_freshness.py [--today YYYY-MM-DD] [--max-age-days 45]

Reads data/driving-test-waits/driving-test-waits-latest.json and driving-test-wait-index/index.html and prints one JSON line.
Exit 0: fresh, or nothing is published yet. Exit 3: the published release is older than --max-age-days (DVSA releases on the
second Wednesday of each month, so the gap between releases is at most 35 days; 45 leaves a week for a late release and
for our own publish), or the page does not state the same month and release date as the files. Run it with the other
checks of docs/release/index-publish-checklist.md; the one-request check of whether DVSA has published something newer is
`fetch_driving_test_waits.py --status`.
This is separate from build-freshness.js on purpose: that file is the weekly shelf-price badge and its tests; nothing in it
is changed.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LATEST = Path('data/driving-test-waits/driving-test-waits-latest.json')
PAGE = Path('driving-test-wait-index/index.html')
MONTH_NAMES = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December')
DATE_RE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}')
MONTH_RE = re.compile(r'[0-9]{4}-(?:0[1-9]|1[0-2])')


def check(root: Path, today: date, max_age_days: int) -> tuple[int, dict]:
    path = root / LATEST
    if not path.exists():
        return 0, {'status': 'not-published'}
    try:
        document = json.loads(path.read_bytes().decode('utf-8'))
        month, vintage = document['month'], document['vintage']
        if not (MONTH_RE.fullmatch(month) and DATE_RE.fullmatch(vintage)):
            raise ValueError
        released = date.fromisoformat(vintage)
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        return 3, {'status': 'unreadable', 'reason': 'the latest file has no readable month and vintage'}
    age = (today - released).days
    facts = {'month': month, 'vintage': vintage, 'ageDays': age, 'maxAgeDays': max_age_days}
    if age < 0:
        return 3, {'status': 'future', **facts}
    if age > max_age_days:
        return 3, {'status': 'stale', **facts}
    try:
        page = html.unescape((root / PAGE).read_text(encoding='utf-8'))
    except OSError:
        return 3, {'status': 'page-missing', **facts}
    stated = f'{MONTH_NAMES[int(month[5:7]) - 1]} {month[:4]}'
    if f'Latest data: {stated}, from the DVSA release of {vintage}' not in page:
        return 3, {'status': 'page-out-of-step', **facts, 'expected': f'{stated}, release {vintage}'}
    return 0, {'status': 'fresh', **facts}


def main(argv: list[str] | None = None, *, root: Path = REPO) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--today', default=None, help='YYYY-MM-DD (default: today, UTC)')
    parser.add_argument('--max-age-days', type=int, default=45)
    args = parser.parse_args(argv)
    try:
        today = date.fromisoformat(args.today) if args.today else datetime.now(UTC).date()
    except ValueError:
        print(json.dumps({'status': 'refused', 'code': 'bad-today'}))
        return 2
    if not 1 <= args.max_age_days <= 400:
        print(json.dumps({'status': 'refused', 'code': 'bad-max-age'}))
        return 2
    code, result = check(root, today, args.max_age_days)
    print(json.dumps(result))
    return code


if __name__ == '__main__':
    sys.exit(main())
