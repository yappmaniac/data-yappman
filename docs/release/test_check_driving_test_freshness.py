"""Tests of check_driving_test_freshness.py on a temp folder (invented files). Run: python -I -B docs/release/test_check_driving_test_freshness.py"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_driving_test_freshness as fresh  # noqa: E402


class Freshness(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix='dtw-fresh-'))
        self.addCleanup(shutil.rmtree, self.dir, True)

    def publish(self, month='2026-10', vintage='2026-11-11', page_has=None) -> None:
        (self.dir / 'data/driving-test-waits').mkdir(parents=True, exist_ok=True)
        (self.dir / fresh.LATEST).write_text(json.dumps({'month': month, 'vintage': vintage}))
        (self.dir / 'driving-test-wait-index').mkdir(exist_ok=True)
        text = page_has if page_has is not None else f'<p>Latest data: October 2026, from the DVSA release of {vintage} (files</p>'
        (self.dir / fresh.PAGE).write_text(text, encoding='utf-8')

    def run_check(self, today: str, *extra: str) -> tuple[int, dict]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = fresh.main(['--today', today, *extra], root=self.dir)
        return code, json.loads(out.getvalue())

    def test_nothing_published_is_fine(self) -> None:
        self.assertEqual(self.run_check('2026-11-26'), (0, {'status': 'not-published'}))

    def test_fresh_until_the_age_limit_then_stale(self) -> None:
        self.publish()
        code, result = self.run_check('2026-11-26')
        self.assertEqual((code, result['status'], result['ageDays']), (0, 'fresh', 15))
        self.assertEqual(self.run_check('2026-12-26')[0], 0)                       # 45 days exactly
        code, result = self.run_check('2026-12-27')
        self.assertEqual((code, result['status']), (3, 'stale'))
        self.assertEqual(self.run_check('2026-12-27', '--max-age-days', '60')[0], 0)

    def test_page_must_state_the_same_month_and_release(self) -> None:
        self.publish(page_has='<p>Latest data: September 2026, from the DVSA release of 2026-10-14 (files</p>')
        code, result = self.run_check('2026-11-26')
        self.assertEqual((code, result['status']), (3, 'page-out-of-step'))
        (self.dir / fresh.PAGE).unlink()
        self.assertEqual(self.run_check('2026-11-26')[1]['status'], 'page-missing')

    def test_unreadable_future_and_bad_arguments(self) -> None:
        self.publish()
        (self.dir / fresh.LATEST).write_text('{"month": "x"}')
        self.assertEqual(self.run_check('2026-11-26')[1]['status'], 'unreadable')
        self.publish(vintage='2026-12-09')
        self.assertEqual(self.run_check('2026-11-26')[1]['status'], 'future')
        self.assertEqual(self.run_check('not-a-date')[0], 2)
        self.assertEqual(self.run_check('2026-11-26', '--max-age-days', '0')[0], 2)

    def test_the_real_page_text_matches_what_the_builder_writes(self) -> None:
        # the sentence this check looks for is the one driving_test_waits_site.render_regions writes
        site = (Path(__file__).resolve().parent / 'driving_test_waits_site.py').read_text(encoding='utf-8')
        self.assertIn("Latest data: {e(month_name(table.month))}, from the DVSA release of {e(table.vintage)}", site)
        self.assertEqual(date(2026, 11, 11).isoformat(), '2026-11-11')


if __name__ == '__main__':
    unittest.main()
