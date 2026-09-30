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

