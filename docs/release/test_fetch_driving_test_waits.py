"""Tests of fetch_driving_test_waits.py on FAKE responses only: no socket is opened, nothing real is downloaded.

    python -I -B docs/release/test_fetch_driving_test_waits.py
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
import urllib.error
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_driving_test_waits as fetch  # noqa: E402
from dvsa_ods_fixture import make_ods  # noqa: E402

NOW = datetime(2026, 11, 26, 19, 0, tzinfo=UTC)
ASSET = 'https://assets.publishing.service.gov.uk/media/{:024x}/{}.ods'
URLS = {t: ASSET.format(i + 1, f'{t}-invented-name') for i, t in enumerate(fetch.TABLES)}


def api_body(**over) -> bytes:
    document = {'public_updated_at': '2026-11-13T09:30:00.000+00:00',
                'details': {'documents': [{'title': f'{t} invented title', 'attachments': [{'url': u, 'file_size': 1000}]}
                                          for t, u in URLS.items()]}}
    document['details']['documents'] = [{'attachments': [{'title': f'{t} invented', 'url': u}]} for t, u in URLS.items()]
    document.update(over)
    return json.dumps(document).encode()


class FakeReply:
    def __init__(self, status: int, body: bytes) -> None:
        self.status, self._body = status, body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, limit: int = -1) -> bytes:
        return self._body if limit < 0 else self._body[:limit]


class FakeOpener:
    """answers by URL: bytes -> 200; an int -> that HTTP status; a list is consumed in turn."""

    def __init__(self, answers: dict[str, object]) -> None:
        self.answers, self.seen = answers, []

    def open(self, request, timeout=None):
        url = request.full_url
        self.seen.append(url)
        answer = self.answers[url]
        if isinstance(answer, list):
            answer = answer.pop(0)
        if isinstance(answer, int):
            raise urllib.error.HTTPError(url, answer, 'x', {}, io.BytesIO(b''))
        return FakeReply(200, answer)


ODS = {t: make_ods({'S': [[t]]}) for t in fetch.TABLES}


def good_answers() -> dict[str, object]:
    return {fetch.API_URL: api_body(), **{URLS[t]: ODS[t] for t in fetch.TABLES}}


class Fetch(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix='dtw-fetch-'))
        (self.dir / 'CNAME').write_text('data.yappman.com\n')
        self.addCleanup(shutil.rmtree, self.dir, True)

    def run_main(self, *args, answers=None, sleeps=None):
        opener = FakeOpener(answers if answers is not None else good_answers())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = fetch.main(list(args), opener=opener, root=self.dir, sleep=(sleeps.append if sleeps is not None else lambda s: None), now=NOW)
        return code, json.loads(out.getvalue()), opener

    def test_dry_run_makes_one_request_and_saves_nothing(self) -> None:
        code, result, opener = self.run_main('--dry-run')
        self.assertEqual((code, result['status'], result['requests']), (0, 'dry-run', 1))
        self.assertEqual(opener.seen, [fetch.API_URL])
        self.assertEqual((result['lastUpdated'], result['releaseDate']), ('2026-11-13', '2026-11-11'))
        self.assertFalse((self.dir / '_incoming').exists())

    def test_fetch_requests_each_file_once_and_saves_with_facts(self) -> None:
        code, result, opener = self.run_main('--fetch')
        self.assertEqual((code, result['status'], result['requests']), (0, 'fetched', 5))
        self.assertEqual(opener.seen, [fetch.API_URL, *(URLS[t] for t in fetch.TABLES)])         # once each, no other URL
        folder = self.dir / '_incoming/driving-test'
        for table in fetch.TABLES:
            self.assertEqual((folder / f'{table}.ods').read_bytes(), ODS[table])
        facts = json.loads((folder / 'FACTS.json').read_text())
        self.assertEqual((facts['v'], facts['releaseDate'], facts['readAt']), (1, '2026-11-11', '2026-11-26T19:00:00Z'))
        self.assertEqual(facts['files']['DRT122F'], {'bytes': len(ODS['DRT122F']), 'sha256': hashlib.sha256(ODS['DRT122F']).hexdigest()})
        self.assertFalse(any(p.name.endswith('.part') for p in folder.iterdir()))
        self.assertNotIn('http', json.dumps(result))                                             # no URL is printed

    def test_a_4xx_stops_the_run_and_saves_nothing(self) -> None:
        answers = good_answers()
        answers[URLS['DRT121G']] = 403
        code, result, opener = self.run_main('--fetch', answers=answers)
        self.assertEqual((code, result['code'], result['httpStatus']), (4, 'blocked-or-not-found', 403))
        self.assertEqual(len(opener.seen), 3)                                                   # API, DRT122F, DRT121G: stopped
        self.assertFalse((self.dir / '_incoming').exists())

    def test_one_retry_after_a_5xx_then_success_and_no_second_retry(self) -> None:
        answers = good_answers()
        answers[URLS['DRT122F']] = [503, ODS['DRT122F']]
        sleeps: list[float] = []
        code, result, opener = self.run_main('--fetch', answers=answers, sleeps=sleeps)
        self.assertEqual((code, result['requests']), (0, 6))
        answers = good_answers()
        answers[URLS['DRT122F']] = [503, 503, ODS['DRT122F']]
        code, result, opener = self.run_main('--fetch', answers=answers)
        self.assertEqual((code, result['code']), (4, 'retries-exhausted'))
        self.assertEqual(opener.seen.count(URLS['DRT122F']), 2)                                 # never a third try

    def test_a_redirect_is_refused(self) -> None:
        answers = good_answers()
        answers[URLS['DRT121A']] = 302
        code, result, _ = self.run_main('--fetch', answers=answers)
        self.assertEqual((code, result['code']), (4, 'redirect-refused'))

    def test_a_reply_that_is_not_an_ods_is_refused(self) -> None:
        answers = good_answers()
        answers[URLS['DRT121B']] = b'<html>blocked</html>'
        code, result, _ = self.run_main('--fetch', answers=answers)
        self.assertEqual((code, result['code']), (3, 'not-a-readable-ods'))
        self.assertFalse((self.dir / '_incoming').exists())

    def test_ambiguous_missing_and_foreign_urls(self) -> None:
        extra = {'attachments': [{'title': 'DRT122F older copy', 'url': ASSET.format(99, 'DRT122F-old')}]}
        document = json.loads(api_body())
        document['details']['documents'].append(extra)
        code, result, _ = self.run_main('--dry-run', answers={fetch.API_URL: json.dumps(document).encode()})
        self.assertEqual((code, result['code']), (3, 'table-not-found-once-DRT122F'))
        document = json.loads(api_body())
        document['details']['documents'] = document['details']['documents'][:-1]
        code, result, _ = self.run_main('--dry-run', answers={fetch.API_URL: json.dumps(document).encode()})
        self.assertEqual((code, result['code']), (3, 'table-not-found-once-DRT121B'))
        document = json.loads(api_body())
        document['details']['documents'][0]['attachments'][0]['url'] = 'https://example.com/media/' + '0' * 24 + '/DRT122F.ods'
        code, result, _ = self.run_main('--dry-run', answers={fetch.API_URL: json.dumps(document).encode()})
        self.assertEqual(code, 3)                                                               # a foreign host is never picked up

    def test_the_transport_refuses_any_other_url(self) -> None:
        transport = fetch.Transport(opener=FakeOpener({}))
        for url in ('https://example.com/a.ods', fetch.API_URL + '?x=1', 'http://www.gov.uk/api/content/x',
                    ASSET.format(1, 'a') + '#frag', 'https://assets.publishing.service.gov.uk/media/zz/DRT122F.ods'):
            with self.assertRaises(fetch.FetchError) as caught:
                transport.get(url, 100)
            self.assertEqual(caught.exception.code, 'url-refused')
        self.assertEqual(transport.requests, 0)

    def test_leftover_part_file_wrong_folder_and_missing_api_date(self) -> None:
        folder = self.dir / '_incoming/driving-test'
        folder.mkdir(parents=True)
        (folder / 'DRT122F.ods.part').write_text('x')
        code, result, opener = self.run_main('--fetch')
        self.assertEqual((code, opener.seen), (5, []))                                          # nothing requested
        shutil.rmtree(self.dir / '_incoming')
        (self.dir / 'CNAME').write_text('other\n')
        self.assertEqual(self.run_main('--dry-run')[0], 2)
        (self.dir / 'CNAME').write_text('data.yappman.com\n')
        body = json.loads(api_body())
        del body['public_updated_at']
        code, result, _ = self.run_main('--dry-run', answers={fetch.API_URL: json.dumps(body).encode()})
        self.assertEqual((code, result['code']), (3, 'last-updated-not-found'))

    def test_release_date_is_the_latest_second_wednesday_not_after_the_update(self) -> None:
        for updated, release in ((date(2026, 11, 13), '2026-11-11'), (date(2026, 11, 11), '2026-11-11'), (date(2026, 12, 3), '2026-11-11'),
                                 (date(2026, 12, 9), '2026-12-09'), (date(2027, 1, 5), '2026-12-09'), (date(2027, 1, 13), '2027-01-13')):
            self.assertEqual(fetch.release_date_for(updated).isoformat(), release, updated)
        self.assertEqual(fetch.second_wednesday(2026, 11), date(2026, 11, 11))


if __name__ == '__main__':
    unittest.main()
