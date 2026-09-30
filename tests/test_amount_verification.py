import glob
import os
import re
import sqlite3
from decimal import Decimal

import pytest

import app as flask_app
from test_phase4_audit import _upload, _form

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ocr(monkeypatch, text):
    monkeypatch.setattr(flask_app.pytesseract, 'image_to_string', lambda *a, **k: text)


def _fee(monkeypatch, fee='₹500', **extra):
    cfg = dict(flask_app.get_event_config(), fee=fee, **extra)
    monkeypatch.setattr(flask_app, 'get_event_config', lambda: cfg)


def _register_with_text(client, monkeypatch, text, roll, color='cyan', **over):
    _ocr(monkeypatch, text)
    prof = _upload(client, 'profile')['token']
    pay = _upload(client, 'payment', color)
    resp = client.post('/', data=_form(prof, pay['token'], roll_number=roll, **over))
    with sqlite3.connect('students.db') as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM students WHERE roll_number=?", (roll,)).fetchone()
    return resp, pay, row


# ── parsing ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize('raw,expected', [
    ('₹500', Decimal('500')), ('Rs. 1,500.50', Decimal('1500.50')), ('INR 250', Decimal('250')),
    (750, Decimal('750')), ('Free entry', None), (None, None),
])
def test_parse_amount(raw, expected):
    assert flask_app.parse_amount(raw) == expected


def test_expected_fee_comes_from_config(monkeypatch):
    _fee(monkeypatch, '₹700')
    assert flask_app.get_expected_fee() == Decimal('700')


def test_fee_amount_key_overrides_display_string(monkeypatch):
    _fee(monkeypatch, 'Rs. five hundred', fee_amount=650)
    assert flask_app.get_expected_fee() == Decimal('650')


@pytest.mark.parametrize('text,expected', [
    ('Payment Successful\n₹500\nTo: Shop', [Decimal('500')]),
    ('Paid Rs.300.00 to Shop', [Decimal('300.00')]),
    ('Amount: 1,250\nUPI Ref No 212111551756', [Decimal('1250')]),
    ('% 500\nCompleted', [Decimal('500')]),          # OCR often misreads the rupee sign
    ('UPI Ref 212111551756\nPhone 9346237108', []),   # ids and phone numbers are not amounts
    ('nothing useful here', []),
])
def test_extract_amounts(text, expected):
    assert flask_app.extract_amounts(text) == expected


@pytest.mark.parametrize('candidates,expected_fee,result', [
    ([Decimal('500')], Decimal('500'), (Decimal('500'), 'exact')),
    ([Decimal('10'), Decimal('500')], Decimal('500'), (Decimal('500'), 'exact')),
    ([Decimal('300')], Decimal('500'), (Decimal('300'), 'under')),
    ([Decimal('700')], Decimal('500'), (Decimal('700'), 'over')),
    ([], Decimal('500'), (None, 'unread')),
    ([Decimal('300')], None, (Decimal('300'), 'unchecked')),
])
def test_classify_amount(candidates, expected_fee, result):
    assert flask_app.classify_amount(candidates, expected_fee) == result


# ── upload feedback ──────────────────────────────────────────────────────────
@pytest.mark.parametrize('text,status', [
    ('Paid ₹500\nUPI Ref 212111551756', 'exact'),
    ('Paid ₹300\nUPI Ref 212111551756', 'under'),
    ('Paid ₹900\nUPI Ref 212111551756', 'over'),
    ('UPI Ref 212111551756', 'unread'),
])
def test_upload_reports_amount_status(client, monkeypatch, text, status):
    _fee(monkeypatch, '₹500')
    _ocr(monkeypatch, text)
    resp = _upload(client, 'payment')
    assert resp['amount_status'] == status
    assert resp['amount_message']
    if status in ('under', 'over'):
        assert '₹500' in resp['amount_message']


# ── registration decisions ───────────────────────────────────────────────────
def test_exact_amount_with_utr_is_confirmed(client, monkeypatch):
    _fee(monkeypatch, '₹500')
    resp, _, row = _register_with_text(client, monkeypatch, 'Paid ₹500\nUPI Ref 212111551756', 'AMT1')
    assert resp.status_code == 302
    assert (row['status'], row['amount_status'], row['amount_paid'], row['amount_expected']) == \
        ('CONFIRMED', 'exact', '500', '500')
    assert not row['review_reason']


@pytest.mark.parametrize('text,status,reason', [
    ('Paid ₹300\nUPI Ref 212111551756', 'under', 'underpaid'),
    ('Paid ₹900\nUPI Ref 212111551756', 'over', 'overpaid'),
    ('UPI Ref 212111551756', 'unread', 'amount not readable'),
])
def test_amount_mismatch_holds_registration_for_review(client, monkeypatch, text, status, reason):
    _fee(monkeypatch, '₹500')
    resp, _, row = _register_with_text(client, monkeypatch, text, 'AMT_' + status.upper())
    assert resp.status_code == 302
    assert row['status'] == 'PENDING'
    assert row['amount_status'] == status
    assert reason in row['review_reason']


def test_fee_change_between_upload_and_submit_is_respected(client, monkeypatch):
    _fee(monkeypatch, '₹500')
    _ocr(monkeypatch, 'Paid ₹500\nUPI Ref 212111551756')
    prof = _upload(client, 'profile')['token']
    pay = _upload(client, 'payment')['token']
    _fee(monkeypatch, '₹600')  # organizer raises the fee before the student submits
    client.post('/', data=_form(prof, pay, roll_number='AMTCHG1'))
    with sqlite3.connect('students.db') as conn:
        row = conn.execute("SELECT status, amount_status FROM students WHERE roll_number='AMTCHG1'").fetchone()
    assert row == ('PENDING', 'under')


def test_unparseable_fee_skips_amount_check(client, monkeypatch):
    _fee(monkeypatch, 'Free')
    resp, _, row = _register_with_text(client, monkeypatch, 'UPI Ref 212111551756', 'AMTFREE1')
    assert row['amount_status'] == 'unchecked' and row['status'] == 'CONFIRMED'


def test_review_reasons_accumulate(client, monkeypatch):
    _fee(monkeypatch, '₹500')
    resp, _, row = _register_with_text(client, monkeypatch, 'Paid ₹300', 'AMTMULTI1', trans_id='MANUALTX123')
    assert row['status'] == 'PENDING' and row['trans_id_source'] == 'manual'
    assert 'underpaid' in row['review_reason'] and 'transaction ID' in row['review_reason']


# ── admin visibility ─────────────────────────────────────────────────────────
def test_admin_pending_list_shows_amounts_and_reason(client, monkeypatch):
    _fee(monkeypatch, '₹500')
    _register_with_text(client, monkeypatch, 'Paid ₹300\nUPI Ref 212111551756', 'AMTADM1')
    with client.session_transaction() as s:
        s['admin_logged_in'] = True
    html = client.get('/admin').get_data(as_text=True)
    pending = html.split('Pending Payment Verifications')[1]
    assert 'AMTADM1' in pending and 'underpaid' in pending
    assert '300' in pending and '500' in pending


# ── the fee is never hardcoded in templates or scripts ───────────────────────
def test_no_hardcoded_currency_amounts_in_templates_or_js():
    files = glob.glob(os.path.join(ROOT, 'templates', '*.html')) + glob.glob(os.path.join(ROOT, 'static', 'js', '*.js'))
    for path in files:
        with open(path, encoding='utf-8') as f:
            assert not re.search(r'(₹|Rs\.?|INR)\s*\d', f.read()), os.path.basename(path)
