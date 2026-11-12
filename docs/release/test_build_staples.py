"""Tests for docs/release/build_staples.py (synthetic data only; no network)."""
import csv
import datetime
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import build_staples as bs  # noqa: E402

SCRIPT = Path(__file__).parent / 'build_staples.py'
COLS = ['retailer', 'retailerProductId', 'price', 'unitPrice/value', 'unitPrice/measure', 'scrapedAt', 'name', 'brand']


def staples_file(tmp_path, products):
    """products: list of (query, retailer, pid)."""
    queries = []
    for q, *_ in products:
        if q not in queries:
            queries.append(q)
    p = tmp_path / 'uk-staples.json'
    p.write_text(json.dumps({'name': 'uk-staples', 'version': 'T', 'builtAt': '2026-09-24', 'queries': queries,
                             'products': [{'query': q, 'retailer': r, 'retailerProductId': i, 'name': 'X'} for q, r, i in products]}), encoding='utf-8')
    return p


def basket_file(tmp_path, rows):
    p = tmp_path / 'basket.csv'
    with open(p, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({**{c: '' for c in COLS}, **r})
    return p


def days(start, n):
    d0 = datetime.date.fromisoformat(start)
    return [(d0 + datetime.timedelta(days=i)).isoformat() for i in range(n)]


def row(r, pid, day, price, uv=None, um=None):
    return {'retailer': r, 'retailerProductId': pid, 'price': str(price), 'unitPrice/value': '' if uv is None else str(uv),
            'unitPrice/measure': um or '', 'scrapedAt': f'{day}T05:30:00.000Z', 'name': 'Secret product', 'brand': 'Secret brand'}


def run(tmp_path, products, rows, min_products=2, min_days=3):
    out = tmp_path / 'out'
    rc = bs.main(['--basket', str(basket_file(tmp_path, rows)), '--staples', str(staples_file(tmp_path, products)),
                  '--min-products', str(min_products), '--min-days', str(min_days), '--out-dir', str(out)])
    weekly = json.loads((out / bs.OUT_WEEKLY).read_text(encoding='utf-8')) if (out / bs.OUT_WEEKLY).exists() else None
    moves = json.loads((out / bs.OUT_MOVES).read_text(encoding='utf-8')) if (out / bs.OUT_MOVES).exists() else None
    return rc, weekly, moves, out


# 2026-W41 is Mon 5 Oct to Sun 11 Oct 2026; 2026-W42 is Mon 12 Oct to Sun 18 Oct
W41, W42 = days('2026-10-05', 7), days('2026-10-12', 7)
PRODUCTS = [('milk', 'tesco', 'a'), ('milk', 'asda', 'b'), ('milk', 'aldi', 'c')]


def milk_rows(price_by_week=None, unit=None):
    price_by_week = price_by_week or {}
    out = []
    for pid, r in (('a', 'tesco'), ('b', 'asda'), ('c', 'aldi')):
        for wk, ds in (('w41', W41), ('w42', W42)):
            pr = price_by_week.get((pid, wk), 1.5)
            for d in ds:
                out.append(row(r, pid, d, pr, *(unit or (pr / 2, 'l'))))
    return out


def test_pooled_median_and_n(tmp_path):
    rows = milk_rows({('a', 'w41'): 1.00, ('b', 'w41'): 1.50, ('c', 'w41'): 2.00})
    rc, weekly, _, _ = run(tmp_path, PRODUCTS, rows)
    assert rc == 0
    s = weekly['staples'][0]
    assert s['id'] == 'milk' and s['basis'] == 'GBP per litre'
    w41 = [x for x in s['series'] if x['week'] == '2026-W41'][0]
    assert w41 == {'week': '2026-W41', 'n': 3, 'medianUnitPrice': 0.75}   # unit prices 0.50, 0.75, 1.00


def test_no_retailer_product_or_url_in_either_file(tmp_path):
    rc, weekly, moves, out = run(tmp_path, PRODUCTS, milk_rows())
    text = (out / bs.OUT_WEEKLY).read_text(encoding='utf-8') + (out / bs.OUT_MOVES).read_text(encoding='utf-8')
    text = text.replace("Tesco, Sainsbury's, Asda and Aldi", '').replace(bs.LICENSE, '')
    for secret in ('Secret product', 'Secret brand', 'tesco', 'asda', 'aldi', 'http'):
        assert secret not in text
    assert bs.check_files(str(out)) == []


def test_week_below_the_floor_is_withheld_not_published(tmp_path):
    rc, weekly, _, _ = run(tmp_path, PRODUCTS, milk_rows(), min_products=4)
    s = weekly['staples'][0]
    assert s['series'] == [] and s['withheld'] == ['2026-W41', '2026-W42'] and s['firstWeek'] is None


def test_product_seen_on_too_few_days_does_not_count(tmp_path):
    rows = [x for x in milk_rows() if not (x['retailerProductId'] == 'c' and x['scrapedAt'][:10] in W42[2:])]  # c has 2 days in W42
    rc, weekly, _, _ = run(tmp_path, PRODUCTS, rows, min_products=3, min_days=3)
    s = weekly['staples'][0]
    assert [x['week'] for x in s['series']] == ['2026-W41'] and s['withheld'] == ['2026-W42']


def test_100g_and_100ml_become_kg_and_litre_and_other_families_are_left_out(tmp_path):
    prods = [('oil', 'tesco', 'a'), ('oil', 'asda', 'b'), ('oil', 'aldi', 'c'), ('oil', 'tesco', 'd')]
    rows = []
    for d in W41:
        rows += [row('tesco', 'a', d, 3, 0.30, '100ml'), row('asda', 'b', d, 3, 3.00, 'l'), row('aldi', 'c', d, 3, 0.90, '100ml'),
                 row('tesco', 'd', d, 3, 0.40, 'each')]
    rc, weekly, _, _ = run(tmp_path, prods, rows, min_products=3)
    s = weekly['staples'][0]
    assert s['basis'] == 'GBP per litre' and s['productsOnOtherUnit'] == 1
    assert s['series'] == [{'week': '2026-W41', 'n': 3, 'medianUnitPrice': 3.0}]   # 3.00, 3.00, 9.00 per litre


def test_moves_count_rose_fell_unchanged(tmp_path):
    rows = milk_rows({('a', 'w42'): 1.60, ('b', 'w42'): 1.40})   # a rose, b fell, c unchanged
    rc, _, moves, _ = run(tmp_path, PRODUCTS, rows)
    assert moves['staples'][0]['weeks'] == [{'week': '2026-W42', 'matched': 3, 'rose': 1, 'fell': 1, 'unchanged': 1}]


def test_moves_need_the_week_before_and_enough_matched_products(tmp_path):
    rc, _, moves, _ = run(tmp_path, PRODUCTS, milk_rows(), min_products=4)
    assert moves['staples'][0]['weeks'] == [] and moves['staples'][0]['withheld'] == ['2026-W42']


def test_rows_for_unknown_products_and_unusable_prices_are_skipped(tmp_path):
    rows = milk_rows() + [row('tesco', 'zzz', W41[0], 2), row('tesco', 'a', W41[0], ''), row('tesco', 'a', W41[1], 'abc'), row('tesco', 'a', W41[1], '-1')]
    rc, weekly, _, _ = run(tmp_path, PRODUCTS, rows)
    assert rc == 0 and weekly['staples'][0]['series'][0]['n'] == 3


def test_two_runs_on_one_day_count_once_and_the_latest_wins(tmp_path):
    # product a is read twice on every day of W41: an early run at 9.99 and a later run at 1.50; only the later one may count
    rows = milk_rows()
    for d in W41:
        early = row('tesco', 'a', d, 9.99, 4.995, 'l')
        early['scrapedAt'] = f'{d}T01:00:00.000Z'
        rows.append(early)
    rc, weekly, moves, _ = run(tmp_path, PRODUCTS, rows)
    w41 = [x for x in weekly['staples'][0]['series'] if x['week'] == '2026-W41'][0]
    assert w41 == {'week': '2026-W41', 'n': 3, 'medianUnitPrice': 0.75}      # 0.75 each, as if the early runs did not exist
    assert [m['rose'] + m['fell'] for m in moves['staples'][0]['weeks']] == [0]


def test_two_rows_with_the_same_timestamp_keep_the_lower_price(tmp_path):
    rows = milk_rows()
    for d in W41:
        dup = row('tesco', 'a', d, 9.99, 4.995, 'l')
        rows.append(dup)                       # same scrapedAt (05:30) as the normal row, higher price
    rc, weekly, _, _ = run(tmp_path, PRODUCTS, rows)
    assert [x for x in weekly['staples'][0]['series'] if x['week'] == '2026-W41'][0]['medianUnitPrice'] == 0.75


def test_notes_carry_the_credit_and_say_posted_not_paid(tmp_path):
    rc, weekly, moves, _ = run(tmp_path, PRODUCTS, milk_rows())
    for d in (weekly, moves):
        assert 'not prices paid' in d['note'] and 'CC BY 4.0' in d['note'] and 'Daily 212-Item Basket' in d['note']
        assert 'latest read counts' in d['note']


def test_bad_date_or_missing_column_stops_the_build(tmp_path):
    rows = milk_rows()
    rows[0]['scrapedAt'] = 'not a date'
    out = tmp_path / 'o'
    rc = bs.main(['--basket', str(basket_file(tmp_path, rows)), '--staples', str(staples_file(tmp_path, PRODUCTS)), '--min-products', '2', '--min-days', '3', '--out-dir', str(out)])
    assert rc == 1 and not out.exists()


def test_the_two_floors_are_required_arguments(tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        bs.main(['--basket', str(basket_file(tmp_path, milk_rows())), '--staples', str(staples_file(tmp_path, PRODUCTS)), '--out-dir', str(tmp_path / 'o')])
    assert e.value.code == 2 and 'required' in capsys.readouterr().err


def test_same_inputs_give_byte_identical_files(tmp_path):
    a = run(tmp_path, PRODUCTS, milk_rows())[3]
    first = (a / bs.OUT_WEEKLY).read_bytes(), (a / bs.OUT_MOVES).read_bytes()
    bs.main(['--basket', str(tmp_path / 'basket.csv'), '--staples', str(tmp_path / 'uk-staples.json'), '--min-products', '2', '--min-days', '3', '--out-dir', str(a)])
    assert first == ((a / bs.OUT_WEEKLY).read_bytes(), (a / bs.OUT_MOVES).read_bytes())
    assert b'\r' not in first[0]


def test_check_finds_a_tampered_file(tmp_path):
    out = run(tmp_path, PRODUCTS, milk_rows())[3]
    p = out / bs.OUT_WEEKLY
    d = json.loads(p.read_text(encoding='utf-8'))
    d['staples'][0]['series'][0]['n'] = 1                                   # below the floor
    p.write_text(bs.dump(d), encoding='utf-8', newline='')
    assert any('below the floor' in x for x in bs.check_files(str(out)))
    d['staples'][0]['series'][0]['n'] = 3
    d['staples'][0]['series'][0]['retailer'] = 'tesco'                      # forbidden key and unexpected keys
    p.write_text(bs.dump(d), encoding='utf-8', newline='')
    probs = bs.check_files(str(out))
    assert any('forbidden keys' in x for x in probs) and any('unexpected keys' in x for x in probs)


def test_check_finds_moves_that_do_not_add_up(tmp_path):
    out = run(tmp_path, PRODUCTS, milk_rows())[3]
    p = out / bs.OUT_MOVES
    d = json.loads(p.read_text(encoding='utf-8'))
    d['staples'][0]['weeks'][0]['rose'] = 2
    p.write_text(bs.dump(d), encoding='utf-8', newline='')
    assert any('is not matched' in x for x in bs.check_files(str(out)))


def test_no_network_is_used(tmp_path, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError('network used')
    monkeypatch.setattr(socket, 'socket', refuse)
    assert run(tmp_path, PRODUCTS, milk_rows())[0] == 0


def test_command_line_check_runs_and_reports(tmp_path):
    out = run(tmp_path, PRODUCTS, milk_rows())[3]
    ok = subprocess.run([sys.executable, '-I', str(SCRIPT), '--check', '--out-dir', str(out)], capture_output=True, text=True)
    assert ok.returncode == 0 and 'well formed' in ok.stdout
    (out / bs.OUT_MOVES).unlink()
    bad = subprocess.run([sys.executable, '-I', str(SCRIPT), '--check', '--out-dir', str(out)], capture_output=True, text=True)
    assert bad.returncode == 1 and 'PROBLEM' in bad.stdout
