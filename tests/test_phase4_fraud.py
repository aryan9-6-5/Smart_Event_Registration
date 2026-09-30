import io
import sqlite3
import pytest
from PIL import Image

import app as flask_app
import email_builder as EB
from test_phase4_audit import _upload, _form


def _login(client):
    with client.session_transaction() as s:
        s['admin_logged_in'] = True


def test_duplicate_payment_screenshot_flagged_as_fraud(client, monkeypatch):
    """Uploading a duplicate screenshot completes registration but sets status to FRAUD."""
    monkeypatch.setattr(flask_app, 'get_expected_fee', lambda: flask_app.Decimal('500'))
    
    # Upload unique profiles
    prof1 = _upload(client, 'profile')['token']
    prof2 = _upload(client, 'profile', color='yellow')['token']

    # Upload identical payment screenshots (same color = identical phash)
    pay1 = _upload(client, 'payment', color='green')['token']
    pay2 = _upload(client, 'payment', color='green')['token']

    # Simulate valid OCR amount so only phash duplicate triggers
    with sqlite3.connect('students.db') as conn:
        conn.execute("UPDATE uploads SET ocr_trans_id = '111122223333', amount_paid = '500' WHERE token = ?", (pay1,))
        conn.execute("UPDATE uploads SET ocr_trans_id = '444455556666', amount_paid = '500' WHERE token = ?", (pay2,))

    # First student registers successfully
    r1 = client.post('/', data=_form(prof1, pay1, roll_number='FRD_ORIG1', trans_id='111122223333'))
    assert r1.status_code == 302

    # Second student with duplicate screenshot completes registration (not blocked on main page)
    r2 = client.post('/', data=_form(prof2, pay2, roll_number='FRD_DUP1', trans_id='444455556666'))
    assert r2.status_code == 302
    success_url = r2.headers['Location']
    assert '/success/' in success_url

    # Check that the database marked them as FRAUD
    with sqlite3.connect('students.db') as conn:
        conn.row_factory = sqlite3.Row
        s2 = conn.execute("SELECT status, review_reason, public_token FROM students WHERE roll_number = 'FRD_DUP1'").fetchone()
        assert s2['status'] == 'FRAUD'
        assert 'duplicate screenshot' in s2['review_reason']

    # Check success page displays fraud alert
    resp_success = client.get(f"/success/{s2['public_token']}")
    html = resp_success.get_data(as_text=True)
    assert 'Fraud Detected / User Flagged for Fraud' in html
    assert 'Your profile is flagged for fraud and is in review' in html


def test_underpaid_amount_flagged_as_fraud(client, monkeypatch):
    """Underpaying fee completes registration but sets status to FRAUD with message on success page."""
    monkeypatch.setattr(flask_app, 'get_expected_fee', lambda: flask_app.Decimal('500'))
    monkeypatch.setattr(flask_app.pytesseract, 'image_to_string', lambda *a, **k: "Paid ₹200\nUPI Ref 998877665544")

    prof = _upload(client, 'profile')['token']
    pay = _upload(client, 'payment', color='purple')['token']

    # Form submission succeeds and redirects to success
    resp = client.post('/', data=_form(prof, pay, roll_number='FRD_UNDER1', trans_id='998877665544'))
    assert resp.status_code == 302

    with sqlite3.connect('students.db') as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status, review_reason, public_token FROM students WHERE roll_number = 'FRD_UNDER1'").fetchone()
        assert row['status'] == 'FRAUD'
        assert 'underpaid' in row['review_reason']

    # Success page displays fraud warning
    html = client.get(f"/success/{row['public_token']}").get_data(as_text=True)
    assert 'Fraud Detected / User Flagged for Fraud' in html
    assert 'Your profile is flagged for fraud and is in review' in html


def test_normal_entry_errors_stay_on_main_page_not_fraud(client, monkeypatch):
    """Normal user errors (duplicate roll, invalid phone, manual trans ID) allow correction on main page."""
    monkeypatch.setattr(flask_app, 'get_expected_fee', lambda: flask_app.Decimal('500'))
    
    # 1. First register student NORM1
    prof1 = _upload(client, 'profile')['token']
    pay1 = _upload(client, 'payment', color='blue')['token']
    with sqlite3.connect('students.db') as conn:
        conn.execute("UPDATE uploads SET ocr_trans_id = '123456789012', amount_paid = '500' WHERE token = ?", (pay1,))
    r1 = client.post('/', data=_form(prof1, pay1, roll_number='NORM1', trans_id='123456789012'))
    assert r1.status_code == 302

    # 2. Try registering again with DUPLICATE roll number -> caught on main page
    prof2 = _upload(client, 'profile')['token']
    pay2 = _upload(client, 'payment', color='red')['token']
    r2 = client.post('/', data=_form(prof2, pay2, roll_number='NORM1', trans_id='999988887777'))
    assert r2.status_code == 200
    assert b"This roll number is already registered" in r2.data

    # 3. Form validation error (invalid phone) -> stays on main page so user can edit
    prof3 = _upload(client, 'profile')['token']
    pay3 = _upload(client, 'payment', color='orange')['token']
    r3 = client.post('/', data=_form(prof3, pay3, roll_number='NORM3', phone='123'))  # invalid phone
    assert r3.status_code == 200
    assert b"Phone number must be exactly 10 digits" in r3.data

    # 4. Manual transaction ID with legitimate payment (non-duplicate, exact amount) -> PENDING (not fraud!)
    prof4 = _upload(client, 'profile')['token']
    
    # Create an image with distinct pattern so it has a different phash from solid colors
    buf4 = io.BytesIO()
    img4 = Image.new('RGB', (100, 100), color='white')
    from PIL import ImageDraw
    draw4 = ImageDraw.Draw(img4)
    draw4.line([(0, 0), (99, 99)], fill='black', width=10)
    img4.save(buf4, 'PNG')
    buf4.seek(0)
    pay4 = client.post('/upload', data={'file': (buf4, 'payment.png'), 'type': 'payment'},
                       content_type='multipart/form-data').get_json()['token']

    with sqlite3.connect('students.db') as conn:
        conn.execute("UPDATE uploads SET ocr_trans_id = NULL, amount_paid = '500' WHERE token = ?", (pay4,))
    r4 = client.post('/', data=_form(prof4, pay4, roll_number='NORM4', trans_id='MANUALOK123'))
    assert r4.status_code == 302

    with sqlite3.connect('students.db') as conn:
        conn.row_factory = sqlite3.Row
        s4 = conn.execute("SELECT status, review_reason FROM students WHERE roll_number = 'NORM4'").fetchone()
        assert s4['status'] == 'PENDING'  # Standard review, NOT fraud!
        assert s4['status'] != 'FRAUD'


def test_fraud_email_content(tmp_path):
    """Email builder creates clear fraud alert in subject and body."""
    placard = tmp_path / 'placard.jpg'
    Image.new('RGB', (100, 100)).save(placard)
    event = {'title': 'Tech Summit 2024', 'date': 'OCT 24'}
    colors = {'primary': '#1E40AF', 'primary_text': '#FFFFFF', 'text': '#0F1B3D', 'muted': '#4F5F82',
              'bg': '#EFF4FC', 'surface': '#FFFFFF', 'border': '#D3DEF2'}
    details = {'name': 'Jane Doe', 'roll_number': 'FRD001', 'ticket_id': 'TECH-FRD001',
               'review_reason': 'duplicate screenshot, underpaid'}

    msg = EB.build_registration_email(sender='admin@test.com', to_email='jane@test.com',
                                      event=event, colors=colors, details=details,
                                      placard_path=str(placard), fraud=True)
    
    assert 'flagged for fraud and is in review' in msg['Subject']
    text = msg.get_body(preferencelist=('plain',)).get_content()
    html = msg.get_body(preferencelist=('html',)).get_content()

    for body in (text, html):
        assert 'Your profile is flagged for fraud and is in review' in body
        assert 'deactivated' in body.lower()


def test_gate_checkin_denies_entry_for_fraud_profile(client):
    """Gate check-in explicitly blocks entry when student status is FRAUD."""
    _login(client)
    ticket_secret = 'fraud_test_secret'
    ticket_id = 'TECH24-FRDBLK1'
    payload = flask_app.sign_ticket(ticket_id, ticket_secret)

    with sqlite3.connect('students.db') as conn:
        conn.execute('''
            INSERT INTO students (name, email, roll_number, trans_id, status, ticket_secret, review_reason)
            VALUES ('Fraud User', 'f@test.com', 'FRDBLK1', 'TXFRD1', 'FRAUD', ?, 'duplicate screenshot')
        ''', (ticket_secret,))

    resp = client.post('/admin/checkin', json={'qr_payload': payload})
    assert resp.status_code == 403
    data = resp.get_json()
    assert 'SECURITY ALERT' in data['message']
    assert 'FRAUD' in data['message']


def test_admin_dashboard_separates_fraud_and_allows_mark_fraud(client):
    """Admin dashboard lists fraud profiles separately and allows marking pending profiles as fraud."""
    _login(client)
    with sqlite3.connect('students.db') as conn:
        conn.execute('''
            INSERT INTO students (name, email, roll_number, trans_id, status, review_reason)
            VALUES ('Pending Student', 'p@test.com', 'PND001', 'TXPND1', 'PENDING', 'transaction ID typed manually')
        ''')
        p_id = conn.execute("SELECT id FROM students WHERE roll_number = 'PND001'").fetchone()[0]

    # Verify pending shows in pending section
    html = client.get('/admin').get_data(as_text=True)
    assert 'PND001' in html
    assert 'Mark Fraud' in html

    # Admin marks this student as fraud
    r_mark = client.post(f'/admin/mark_fraud/{p_id}', follow_redirects=True)
    assert r_mark.status_code == 200

    with sqlite3.connect('students.db') as conn:
        row = conn.execute("SELECT status, review_reason FROM students WHERE id = ?", (p_id,)).fetchone()
        assert row[0] == 'FRAUD'
        assert 'flagged by admin' in row[1]

    # Admin dashboard now reflects fraud count
    html2 = client.get('/admin').get_data(as_text=True)
    assert 'data-stat="fraud">1<' in html2

    # Admin overrides and approves the fraud student
    r_app = client.post(f'/admin/approve/{p_id}', follow_redirects=True)
    assert r_app.status_code == 200

    with sqlite3.connect('students.db') as conn:
        assert conn.execute("SELECT status FROM students WHERE id = ?", (p_id,)).fetchone()[0] == 'CONFIRMED'


def test_reused_payment_screenshot_with_same_trans_id_not_blocked_on_main_page(client, monkeypatch):
    """When a payment proof has identical screenshot and identical trans_id, it completes registration and flags as FRAUD."""
    monkeypatch.setattr(flask_app, 'get_expected_fee', lambda: flask_app.Decimal('500'))

    prof1 = _upload(client, 'profile')['token']
    prof2 = _upload(client, 'profile', color='yellow')['token']

    pay1 = _upload(client, 'payment', color='green')['token']
    pay2 = _upload(client, 'payment', color='green')['token']

    with sqlite3.connect('students.db') as conn:
        conn.execute("UPDATE uploads SET ocr_trans_id = 'SAME99988877', amount_paid = '500' WHERE token = ?", (pay1,))
        conn.execute("UPDATE uploads SET ocr_trans_id = 'SAME99988877', amount_paid = '500' WHERE token = ?", (pay2,))

    r1 = client.post('/', data=_form(prof1, pay1, roll_number='SAME_TXN1', trans_id='SAME99988877'))
    assert r1.status_code == 302

    # Second student uploads the same receipt / enters the same transaction ID
    r2 = client.post('/', data=_form(prof2, pay2, roll_number='SAME_TXN2', trans_id='SAME99988877'))
    assert r2.status_code == 302
    assert '/success/' in r2.headers['Location']

    with sqlite3.connect('students.db') as conn:
        conn.row_factory = sqlite3.Row
        s2 = conn.execute("SELECT status, review_reason, public_token FROM students WHERE roll_number = 'SAME_TXN2'").fetchone()
        assert s2['status'] == 'FRAUD'
        assert 'duplicate screenshot' in s2['review_reason']
        assert 'duplicate transaction ID' in s2['review_reason']

    resp = client.get(f"/success/{s2['public_token']}")
    html = resp.get_data(as_text=True)
    assert 'Fraud Detected / User Flagged for Fraud' in html
    assert 'Your profile is flagged for fraud and is in review' in html
