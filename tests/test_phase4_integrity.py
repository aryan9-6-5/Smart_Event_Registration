import sqlite3

import app as flask_app
from test_phase4_audit import _upload, _form, _register


# ── Item 5: admin authentication ─────────────────────────────────────────────
def test_admin_login_disabled_when_no_credentials_configured(client, monkeypatch):
    monkeypatch.setattr(flask_app, 'ADMIN_PASSWORD_HASH', None, raising=False)
    monkeypatch.setattr(flask_app, 'ADMIN_PASSWORD', None, raising=False)
    for pw in ('admin123', '', 'admin'):
        resp = client.post('/admin/login', data={'username': 'admin', 'password': pw})
        assert resp.status_code == 200 and b'Invalid credentials' in resp.data


def test_admin_login_uses_password_hash(client, monkeypatch):
    from werkzeug.security import generate_password_hash
    monkeypatch.setattr(flask_app, 'ADMIN_PASSWORD_HASH', generate_password_hash('s3cret-pw'), raising=False)
    monkeypatch.setattr(flask_app, 'ADMIN_PASSWORD', None, raising=False)
    bad = client.post('/admin/login', data={'username': 'admin', 'password': 'wrong'})
    assert bad.status_code == 200
    good = client.post('/admin/login', data={'username': 'admin', 'password': 's3cret-pw'})
    assert good.status_code == 302


def test_session_cookie_hardening(app):
    assert app.config['SESSION_COOKIE_HTTPONLY'] is True
    assert app.config['SESSION_COOKIE_SAMESITE'] == 'Lax'


# ── Item 6: upload tokens are single-use and consumed atomically ─────────────
def test_upload_tokens_consumed_after_registration(client):
    resp, prof, pay = _register(client, roll_number='ONCE1')
    assert resp.status_code == 302
    with sqlite3.connect('students.db') as conn:
        left = conn.execute("SELECT COUNT(*) FROM uploads WHERE token IN (?,?)", (prof, pay)).fetchone()[0]
    assert left == 0


def test_registration_rejected_if_tokens_consumed_mid_flight(client, monkeypatch):
    prof = _upload(client, 'profile')['token']
    pay = _upload(client, 'payment', 'red')['token']

    def steal_tokens(n):
        with sqlite3.connect('students.db') as conn:
            conn.execute("DELETE FROM uploads WHERE token IN (?,?)", (prof, pay))
        return 'ab' * 16

    monkeypatch.setattr(flask_app.secrets, 'token_hex', steal_tokens)
    resp = client.post('/', data=_form(prof, pay, roll_number='RACE1'))
    assert resp.status_code == 200
    with sqlite3.connect('students.db') as conn:
        assert conn.execute("SELECT COUNT(*) FROM students WHERE roll_number='RACE1'").fetchone()[0] == 0


# ── Item 7: PENDING attendees are not told they are confirmed ────────────────
def test_success_page_reflects_pending_status(client):
    resp, _, _ = _register(client, roll_number='PENDMSG1')
    page = client.get(resp.headers['Location'])
    assert b'pending' in page.data.lower() and b'has been confirmed' not in page.data


def test_success_page_confirmed_message_for_confirmed(client):
    resp, _, _ = _register(client, roll_number='CONFMSG1')
    with sqlite3.connect('students.db') as conn:
        conn.execute("UPDATE students SET status='CONFIRMED' WHERE roll_number='CONFMSG1'")
    page = client.get(resp.headers['Location'])
    assert b'has been confirmed' in page.data


# ── Item 8: email retry, admin resend, notify on approval ────────────────────
def test_send_email_async_retries_before_failing(monkeypatch):
    calls = []
    monkeypatch.setattr(flask_app, 'send_email', lambda *a, **k: calls.append(1) or False)
    monkeypatch.setattr(flask_app, 'EMAIL_RETRY_DELAYS', (0, 0), raising=False)
    with sqlite3.connect('students.db') as conn:
        conn.execute("INSERT INTO students (name,email,roll_number,trans_id,status) "
                     "VALUES ('R','r@x.com','RETRY1','T1','CONFIRMED')")
        sid = conn.execute("SELECT id FROM students WHERE roll_number='RETRY1'").fetchone()[0]
    assert flask_app.send_email_async(sid, 'r@x.com', 'p.jpg') is False
    assert len(calls) == 3
    with sqlite3.connect('students.db') as conn:
        assert conn.execute("SELECT email_status FROM students WHERE id=?", (sid,)).fetchone()[0] == 'failed'


def _seed_student(status='CONFIRMED', roll='RSND1'):
    with sqlite3.connect('students.db') as conn:
        conn.execute("INSERT INTO students (name,email,roll_number,trans_id,status,placard_path,email_status) "
                     "VALUES ('S','s@x.com',?,?,?,'p.jpg','failed')", (roll, 'T' + roll, status))
        return conn.execute("SELECT id FROM students WHERE roll_number=?", (roll,)).fetchone()[0]


def _login(client):
    with client.session_transaction() as s:
        s['admin_logged_in'] = True


def test_admin_resend_requires_login_and_queues_email(client, monkeypatch):
    sid = _seed_student()
    queued = []
    monkeypatch.setattr(flask_app.EMAIL_EXECUTOR, 'submit', lambda fn, *a, **k: queued.append(a))
    assert client.post(f'/admin/resend/{sid}').status_code == 302
    assert not queued
    _login(client)
    assert client.post(f'/admin/resend/{sid}').status_code == 302
    assert len(queued) == 1
    with sqlite3.connect('students.db') as conn:
        assert conn.execute("SELECT email_status FROM students WHERE id=?", (sid,)).fetchone()[0] == 'pending'


def test_admin_resend_skips_rejected(client, monkeypatch):
    sid = _seed_student('REJECTED', 'RSND2')
    queued = []
    monkeypatch.setattr(flask_app.EMAIL_EXECUTOR, 'submit', lambda fn, *a, **k: queued.append(a))
    _login(client)
    client.post(f'/admin/resend/{sid}')
    assert not queued


def test_approve_only_affects_pending_and_sends_email(client, monkeypatch):
    pend = _seed_student('PENDING', 'APR1')
    rej = _seed_student('REJECTED', 'APR2')
    queued = []
    monkeypatch.setattr(flask_app.EMAIL_EXECUTOR, 'submit', lambda fn, *a, **k: queued.append(a))
    _login(client)
    client.post(f'/admin/approve/{pend}')
    client.post(f'/admin/approve/{rej}')
    with sqlite3.connect('students.db') as conn:
        st = dict(conn.execute("SELECT id,status FROM students").fetchall())
    assert st[pend] == 'CONFIRMED' and st[rej] == 'REJECTED'
    assert len(queued) == 1


# ── Item 9: no internal error text leaked to the browser ─────────────────────
def test_unexpected_error_does_not_leak_details(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError('SECRET-INTERNAL-PATH')
    monkeypatch.setattr(flask_app, 'generate_placard', boom)
    resp, _, _ = _register(client, roll_number='LEAK1')
    assert resp.status_code == 200
    assert b'SECRET-INTERNAL-PATH' not in resp.data
    with sqlite3.connect('students.db') as conn:
        assert conn.execute("SELECT COUNT(*) FROM students WHERE roll_number='LEAK1'").fetchone()[0] == 0


# ── Item 10: duplicate transaction IDs are flagged as FRAUD, not blocked on main page ──
def test_trans_id_uniqueness_is_case_insensitive(client):
    r1, _, _ = _register(client, roll_number='CASE1', trans_id='abcde12345')
    r2, _, _ = _register(client, 'red', roll_number='CASE2', trans_id='ABCDE12345')
    assert r1.status_code == 302
    # Duplicate transaction ID must complete registration and flag as FRAUD (never block on main page)
    assert r2.status_code == 302
    assert '/success/' in r2.headers['Location']
    with sqlite3.connect('students.db') as conn:
        conn.row_factory = sqlite3.Row
        s2 = conn.execute("SELECT status, review_reason, public_token FROM students WHERE roll_number = 'CASE2'").fetchone()
        assert s2['status'] == 'FRAUD'
        assert 'duplicate transaction ID' in s2['review_reason']

    resp = client.get(f"/success/{s2['public_token']}")
    assert b'Fraud Detected / User Flagged for Fraud' in resp.data
    assert b'Your profile is flagged for fraud and is in review' in resp.data
