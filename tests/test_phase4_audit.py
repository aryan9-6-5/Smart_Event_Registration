import io
import os
import sqlite3
import pytest
from PIL import Image

import app as flask_app


def _upload(client, kind, color='cyan'):
    buf = io.BytesIO()
    Image.new('RGB', (100, 100), color=color).save(buf, 'PNG')
    buf.seek(0)
    resp = client.post('/upload', data={'file': (buf, f'{kind}.png'), 'type': kind},
                       content_type='multipart/form-data')
    return resp.get_json()


def _form(prof, pay, **over):
    roll = over.get('roll_number', 'AUD001')
    email_default = f"{roll.lower()}@example.com" if roll else 'a@example.com'
    data = {
        'name': 'Audit User', 'email': email_default, 'roll_number': 'AUD001',
        'dept_name': 'CSE', 'college_name': 'College', 'trans_id': 'MANUAL12345',
        'phone': '9876543210', 'profile_token': prof, 'payment_token': pay,
    }
    data.update(over)
    return data


def _register(client, color='cyan', **over):
    prof = _upload(client, 'profile')['token']
    pay = _upload(client, 'payment', color)['token']
    return client.post('/', data=_form(prof, pay, **over)), prof, pay


# ── Item 1: roll number path traversal ───────────────────────────────────────
@pytest.mark.parametrize('bad', ['../../PWN', r'..\..\PWN', 'A/B', 'AB C', 'A.B'])
def test_roll_number_rejects_path_characters(client, bad):
    resp, _, _ = _register(client, roll_number=bad)
    assert resp.status_code == 200  # form re-rendered with validation error
    with sqlite3.connect('students.db') as conn:
        assert conn.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 0
    root = os.path.dirname(os.path.abspath(flask_app.STORAGE_DIR))
    assert not [f for f in os.listdir(root) if 'PWN' in f]


# ── Item 2: OCR strictness ───────────────────────────────────────────────────
def test_ocr_random_word_is_not_a_confident_transaction_id(monkeypatch, dummy_image):
    monkeypatch.setattr(flask_app.pytesseract, 'image_to_string', lambda *a, **k: "Payment Successful")
    trans_id, confident = flask_app.extract_transaction_id(dummy_image)
    assert confident is False


def test_ocr_twelve_digit_utr_is_confident(monkeypatch, dummy_image):
    monkeypatch.setattr(flask_app.pytesseract, 'image_to_string',
                        lambda *a, **k: "UPI Ref No: 123456789012\nPaid")
    assert flask_app.extract_transaction_id(dummy_image) == ('123456789012', True)


def test_ocr_fallback_word_not_stored_as_ocr_trans_id(client, monkeypatch):
    monkeypatch.setattr(flask_app.pytesseract, 'image_to_string', lambda *a, **k: "Payment Successful")
    resp, _, _ = _register(client, roll_number='OCRW1', trans_id='REALTXN12345')
    assert resp.status_code == 302
    with sqlite3.connect('students.db') as conn:
        row = conn.execute("SELECT trans_id, trans_id_source, status FROM students WHERE roll_number='OCRW1'").fetchone()
    assert row == ('REALTXN12345', 'manual', 'PENDING')


# ── Item 3: check-in must not hit the default rate limit ─────────────────────
def test_checkin_not_throttled_by_default_limit(client):
    flask_app.limiter.enabled = True
    flask_app.limiter.reset()
    try:
        with client.session_transaction() as s:
            s['admin_logged_in'] = True
        codes = [client.post('/admin/checkin', json={'qr_payload': 'X.Y'}).status_code for _ in range(120)]
        assert 429 not in codes
    finally:
        flask_app.limiter.enabled = False


# ── Item 4: open redirect on admin login ─────────────────────────────────────
@pytest.mark.parametrize('nxt', ['//evil.example/x', 'https://evil.example', '\\evil.example', 'javascript:alert(1)'])
def test_admin_login_rejects_offsite_next(client, monkeypatch, nxt):
    monkeypatch.setattr(flask_app, 'ADMIN_PASSWORD_HASH', None, raising=False)
    monkeypatch.setattr(flask_app, 'ADMIN_PASSWORD', 'pw-for-tests')
    resp = client.post('/admin/login', query_string={'next': nxt},
                       data={'username': flask_app.ADMIN_USERNAME, 'password': 'pw-for-tests'})
    assert resp.status_code == 302
    assert resp.headers['Location'].startswith('/admin')


def test_admin_login_follows_local_next(client, monkeypatch):
    monkeypatch.setattr(flask_app, 'ADMIN_PASSWORD_HASH', None, raising=False)
    monkeypatch.setattr(flask_app, 'ADMIN_PASSWORD', 'pw-for-tests')
    resp = client.post('/admin/login', query_string={'next': '/admin/checkin'},
                       data={'username': flask_app.ADMIN_USERNAME, 'password': 'pw-for-tests'})
    assert resp.headers['Location'].endswith('/admin/checkin')


def test_duplicate_email_rejected_on_main_page(client):
    r1, _, _ = _register(client, roll_number='UNIQEMAIL1', email='same@example.com')
    assert r1.status_code == 302

    r2, _, _ = _register(client, 'red', roll_number='UNIQEMAIL2', email='same@example.com')
    assert r2.status_code == 200
    assert b'This email is already registered' in r2.data

