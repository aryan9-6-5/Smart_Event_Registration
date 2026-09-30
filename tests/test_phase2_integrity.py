import sqlite3
import pytest

def test_students_table_schema_has_new_columns(app):
    """Test: Additive schema migration adds status, ocr_trans_id, trans_id_source, payment_phash, email_status, checked_in_at, ticket_secret."""
    with sqlite3.connect('students.db') as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(students)")
        columns = {row[1] for row in cursor.fetchall()}

    expected_columns = {
        'public_token',
        'status',
        'ocr_trans_id',
        'trans_id_source',
        'payment_phash',
        'email_status',
        'checked_in_at',
        'ticket_secret'
    }
    missing = expected_columns - columns
    assert not missing, f"Missing columns in students table: {missing}"

def test_concurrent_duplicate_registration(client):
    """Test: Two simultaneous registration requests for the same roll number result in exactly 1 row and 1 set of files."""
    import concurrent.futures
    import io
    from PIL import Image

    def get_token(kind):
        file_bytes = io.BytesIO()
        img = Image.new('RGB', (100, 100), color='cyan')
        img.save(file_bytes, 'PNG')
        file_bytes.seek(0)
        resp = client.post('/upload', data={'file': (file_bytes, f'{kind}.png'), 'type': kind}, content_type='multipart/form-data')
        return resp.get_json()['token']

    prof1 = get_token('profile')
    pay1 = get_token('payment')
    prof2 = get_token('profile')
    pay2 = get_token('payment')

    data1 = {
        'name': 'Concurrent Student 1',
        'email': 'c1@example.com',
        'roll_number': 'CONCURR001',
        'dept_name': 'CSE',
        'college_name': 'College',
        'trans_id': 'TXNCONC001',
        'phone': '9876543210',
        'profile_token': prof1,
        'payment_token': pay1
    }

    data2 = {
        'name': 'Concurrent Student 2',
        'email': 'c2@example.com',
        'roll_number': 'CONCURR001',  # Same roll number
        'dept_name': 'CSE',
        'college_name': 'College',
        'trans_id': 'TXNCONC002',
        'phone': '9876543211',
        'profile_token': prof2,
        'payment_token': pay2
    }

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(lambda: client.post('/', data=data1, follow_redirects=False))
        f2 = executor.submit(lambda: client.post('/', data=data2, follow_redirects=False))
        results = [f1.result(), f2.result()]

    statuses = [r.status_code for r in results]
    # Exactly one should succeed with 302, the other rejected with 200 (error banner)
    assert statuses.count(302) == 1
    assert statuses.count(200) == 1

    with sqlite3.connect('students.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM students WHERE roll_number = 'CONCURR001'")
        count = cursor.fetchone()[0]
        assert count == 1


def test_server_controlled_trans_id_overrides_client(client):
    """Test: When OCR extracts a trans_id, it overrides any tampered client-submitted trans_id."""
    import io
    from PIL import Image

    def get_token(kind):
        file_bytes = io.BytesIO()
        img = Image.new('RGB', (100, 100), color='cyan')
        img.save(file_bytes, 'PNG')
        file_bytes.seek(0)
        resp = client.post('/upload', data={'file': (file_bytes, f'{kind}.png'), 'type': kind}, content_type='multipart/form-data')
        return resp.get_json()['token']

    prof_token = get_token('profile')
    pay_token = get_token('payment')

    # Simulate OCR having extracted a valid UPI UTR
    with sqlite3.connect('students.db') as conn:
        conn.execute("UPDATE uploads SET ocr_trans_id = '987654321098' WHERE token = ?", (pay_token,))

    # Client tries to tamper with trans_id in POST body
    data = {
        'name': 'OCR Test User',
        'email': 'ocr@example.com',
        'roll_number': 'OCR001',
        'dept_name': 'CSE',
        'college_name': 'Engineering College',
        'trans_id': 'CLIENTTAMPERED123',
        'phone': '9876543210',
        'profile_token': prof_token,
        'payment_token': pay_token
    }
    resp = client.post('/', data=data, follow_redirects=False)
    assert resp.status_code == 302

    with sqlite3.connect('students.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT trans_id, ocr_trans_id, trans_id_source, status FROM students WHERE roll_number = 'OCR001'")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == '987654321098'  # Server-enforced OCR ID, not client's tampered ID
        assert row[1] == '987654321098'
        assert row[2] == 'ocr'
        assert row[3] == 'CONFIRMED'

def test_manual_trans_id_fallback_sets_status_pending(client):
    """Test: When OCR fails, manual entry is accepted but status is set to PENDING."""
    import io
    from PIL import Image

    def get_token(kind):
        file_bytes = io.BytesIO()
        img = Image.new('RGB', (100, 100), color='cyan')
        img.save(file_bytes, 'PNG')
        file_bytes.seek(0)
        resp = client.post('/upload', data={'file': (file_bytes, f'{kind}.png'), 'type': kind}, content_type='multipart/form-data')
        return resp.get_json()['token']

    prof_token = get_token('profile')
    pay_token = get_token('payment')

    # Ensure uploads has ocr_trans_id as NULL
    with sqlite3.connect('students.db') as conn:
        conn.execute("UPDATE uploads SET ocr_trans_id = NULL WHERE token = ?", (pay_token,))

    data = {
        'name': 'Manual Test User',
        'email': 'manual@example.com',
        'roll_number': 'MAN001',
        'dept_name': 'CSE',
        'college_name': 'Engineering College',
        'trans_id': 'MANUAL123456',
        'phone': '9876543210',
        'profile_token': prof_token,
        'payment_token': pay_token
    }
    resp = client.post('/', data=data, follow_redirects=False)
    assert resp.status_code == 302

    with sqlite3.connect('students.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT trans_id, ocr_trans_id, trans_id_source, status FROM students WHERE roll_number = 'MAN001'")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == 'MANUAL123456'
        assert row[1] is None
        assert row[2] == 'manual'
        assert row[3] == 'PENDING'

def test_invalid_manual_trans_id_rejected(client):
    """Test: Manual trans_id with invalid characters is rejected by form validation."""
    import io
    from PIL import Image

    def get_token(kind):
        file_bytes = io.BytesIO()
        img = Image.new('RGB', (100, 100), color='cyan')
        img.save(file_bytes, 'PNG')
        file_bytes.seek(0)
        resp = client.post('/upload', data={'file': (file_bytes, f'{kind}.png'), 'type': kind}, content_type='multipart/form-data')
        return resp.get_json()['token']

    prof_token = get_token('profile')
    pay_token = get_token('payment')

    data = {
        'name': 'Invalid Trans ID',
        'email': 'bad_trans@example.com',
        'roll_number': 'BADTXN001',
        'dept_name': 'CSE',
        'college_name': 'Engineering College',
        'trans_id': 'BAD!@#$ID',
        'phone': '9876543210',
        'profile_token': prof_token,
        'payment_token': pay_token
    }
    resp = client.post('/', data=data, follow_redirects=False)
    assert resp.status_code == 200
    assert b"Transaction ID must be alphanumeric" in resp.data

def test_duplicate_payment_screenshot_flagged_as_pending(client):
    """Test: Uploading an identical/duplicate payment screenshot flags the new registration as PENDING."""
    import io
    from PIL import Image

    # Upload unique profile
    def upload_img(color, kind):
        buf = io.BytesIO()
        img = Image.new('RGB', (120, 120), color=color)
        img.save(buf, 'PNG')
        buf.seek(0)
        resp = client.post('/upload', data={'file': (buf, f'{kind}.png'), 'type': kind}, content_type='multipart/form-data')
        return resp.get_json()['token']

    prof1 = upload_img('red', 'profile')
    prof2 = upload_img('blue', 'profile')

    # Upload exact same payment screenshot twice
    pay1 = upload_img('green', 'payment')
    pay2 = upload_img('green', 'payment')

    # Both simulated as having valid OCR extracted IDs (so otherwise they would be CONFIRMED)
    with sqlite3.connect('students.db') as conn:
        conn.execute("UPDATE uploads SET ocr_trans_id = '111122223333' WHERE token = ?", (pay1,))
        conn.execute("UPDATE uploads SET ocr_trans_id = '444455556666' WHERE token = ?", (pay2,))

    # First student registers with pay1
    resp1 = client.post('/', data={
        'name': 'Student One',
        'email': 's1@example.com',
        'roll_number': 'DUP001',
        'dept_name': 'CSE',
        'college_name': 'Engineering College',
        'trans_id': '111122223333',
        'phone': '9876543210',
        'profile_token': prof1,
        'payment_token': pay1
    }, follow_redirects=False)
    assert resp1.status_code == 302

    with sqlite3.connect('students.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, payment_phash FROM students WHERE roll_number = 'DUP001'")
        s1_status, s1_phash = cursor.fetchone()
        assert s1_status == 'CONFIRMED'
        assert s1_phash is not None

    # Second student registers with duplicate payment image pay2
    resp2 = client.post('/', data={
        'name': 'Student Two',
        'email': 's2@example.com',
        'roll_number': 'DUP002',
        'dept_name': 'CSE',
        'college_name': 'Engineering College',
        'trans_id': '444455556666',
        'phone': '9876543211',
        'profile_token': prof2,
        'payment_token': pay2
    }, follow_redirects=False)
    assert resp2.status_code == 302

    with sqlite3.connect('students.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, payment_phash FROM students WHERE roll_number = 'DUP002'")
        s2_status, s2_phash = cursor.fetchone()
        # Even though OCR found a trans_id, duplicate payment image forces status to PENDING
        assert s2_status == 'PENDING'
        assert s2_phash == s1_phash

def test_signed_qr_payload_generation_and_verification(app):
    """Test: sign_ticket produces an HMAC signed payload and verify_ticket_signature validates it."""
    import app as flask_app

    ticket_id = "TECH24-ROLL001"
    secret = "random_ticket_secret_123"

    signed_payload = flask_app.sign_ticket(ticket_id, ticket_secret=secret)
    assert signed_payload.startswith("TECH24-ROLL001.")
    parts = signed_payload.split('.')
    assert len(parts) == 2
    assert len(parts[1]) == 16  # 16-char hex truncated hmac

    # Authentic payload verification passes
    is_valid, extracted_id = flask_app.verify_ticket_signature(signed_payload, ticket_secret=secret)
    assert is_valid is True
    assert extracted_id == ticket_id

    # Forged signature fails
    forged_payload = f"{ticket_id}.0123456789abcdef"
    is_valid, _ = flask_app.verify_ticket_signature(forged_payload, ticket_secret=secret)
    assert is_valid is False

    # Wrong secret fails
    is_valid, _ = flask_app.verify_ticket_signature(signed_payload, ticket_secret="wrong_secret")
    assert is_valid is False

    # Tampered ticket ID fails
    tampered_payload = f"TECH24-ROLL999.{parts[1]}"
    is_valid, _ = flask_app.verify_ticket_signature(tampered_payload, ticket_secret=secret)
    assert is_valid is False

def test_registration_generates_and_stores_ticket_secret(client):
    """Test: When a student registers, ticket_secret is securely generated and persisted in the database."""
    import io
    from PIL import Image

    def get_token(kind):
        buf = io.BytesIO()
        img = Image.new('RGB', (100, 100), color='cyan')
        img.save(buf, 'PNG')
        buf.seek(0)
        resp = client.post('/upload', data={'file': (buf, f'{kind}.png'), 'type': kind}, content_type='multipart/form-data')
        return resp.get_json()['token']

    prof = get_token('profile')
    pay = get_token('payment')

    data = {
        'name': 'Signed QR Student',
        'email': 'qr@example.com',
        'roll_number': 'QRSEC001',
        'dept_name': 'CSE',
        'college_name': 'Engineering College',
        'trans_id': 'TXNQRSEC001',
        'phone': '9876543210',
        'profile_token': prof,
        'payment_token': pay
    }
    resp = client.post('/', data=data, follow_redirects=False)
    assert resp.status_code == 302

    with sqlite3.connect('students.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ticket_secret FROM students WHERE roll_number = 'QRSEC001'")
        row = cursor.fetchone()
        assert row is not None
        ticket_secret = row[0]
        assert ticket_secret is not None
        assert len(ticket_secret) >= 16

def test_admin_portal_unauthenticated_redirect(client):
    """Test: Accessing /admin unauthenticated redirects to /admin/login."""
    resp = client.get('/admin', follow_redirects=False)
    assert resp.status_code == 302
    assert '/admin/login' in resp.headers.get('Location', '')

def test_admin_portal_login_and_actions(client):
    """Test: Admin login, viewing pending registrations, approving, rejecting, and searching."""
    # 1. Failed login with wrong password
    bad_login = client.post('/admin/login', data={'username': 'admin', 'password': 'wrongpassword'}, follow_redirects=False)
    assert bad_login.status_code == 200
    assert b"Invalid credentials" in bad_login.data

    # 2. Successful login
    good_login = client.post('/admin/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
    assert good_login.status_code == 302
    assert '/admin' in good_login.headers.get('Location', '')

    # Insert test pending student and confirmed student
    with sqlite3.connect('students.db') as conn:
        conn.execute('''
            INSERT INTO students (name, email, roll_number, dept_name, college_name, trans_id, phone, status)
            VALUES ('Pending Student', 'pending@test.com', 'PEND001', 'CSE', 'Test College', 'TXNPEND123', '9876543210', 'PENDING')
        ''')
        pending_id = conn.execute("SELECT id FROM students WHERE roll_number = 'PEND001'").fetchone()[0]

    # 3. Access admin dashboard - should show pending student
    dash = client.get('/admin')
    assert dash.status_code == 200
    assert b"PEND001" in dash.data
    assert b"TXNPEND123" in dash.data

    # 4. Approve student
    approve_resp = client.post(f'/admin/approve/{pending_id}', follow_redirects=False)
    assert approve_resp.status_code in (200, 302)

    with sqlite3.connect('students.db') as conn:
        status = conn.execute("SELECT status FROM students WHERE id = ?", (pending_id,)).fetchone()[0]
        assert status == 'CONFIRMED'

    # 5. Reject student
    reject_resp = client.post(f'/admin/reject/{pending_id}', follow_redirects=False)
    assert reject_resp.status_code in (200, 302)

    with sqlite3.connect('students.db') as conn:
        status = conn.execute("SELECT status FROM students WHERE id = ?", (pending_id,)).fetchone()[0]
        assert status == 'REJECTED'

    # 6. Admin search
    search_resp = client.get('/admin?q=PEND001')
    assert search_resp.status_code == 200
    assert b"Pending Student" in search_resp.data




