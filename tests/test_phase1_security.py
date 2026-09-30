def test_test_route_is_removed(client):
    """Bug test: /test backdoor route must not exist and should return 404."""
    response = client.get('/test')
    assert response.status_code == 404

def test_name_equals_test_does_not_bypass_validation(client):
    """Bug test: name='test' in form submission must not bypass validation or redirect."""
    response = client.post('/', data={'name': 'test'})
    # It should fail validation and render index.html with errors (200), not 302 redirect
    assert response.status_code == 200
    assert b"Registration Form" in response.data
    # Should contain validation error or form errors, not redirect to success
    assert response.headers.get('Location') is None

def test_no_secret_in_source_or_stdout():
    """Bug test: app.py must not contain print statements leaking SMTP secrets."""
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()
    assert 'print("USING:",' not in content
    assert 'print(\'USING:\',' not in content

def test_static_url_path_is_prefixed(app):
    """Bug test: static_url_path must be '/static' and not '' to prevent root static exposure."""
    assert app.static_url_path == '/static'

def test_storage_directories_exist():
    """Verify that private storage directories exist outside static."""
    import os
    for sub in ['tmp', 'profiles', 'payments', 'placards', 'tickets']:
        path = os.path.join('storage', sub)
        assert os.path.isdir(path), f"Expected directory {path} to exist"

def test_upload_returns_token_and_inserts_in_uploads_table(client):
    """Test that /upload returns an opaque token and records it in the uploads table."""
    import io
    import sqlite3
    from PIL import Image

    file_bytes = io.BytesIO()
    img = Image.new('RGB', (100, 100), color='purple')
    img.save(file_bytes, 'PNG')
    file_bytes.seek(0)

    resp = client.post('/upload', data={
        'file': (file_bytes, 'profile.png'),
        'type': 'profile'
    }, content_type='multipart/form-data')

    assert resp.status_code == 200
    data = resp.get_json()
    assert 'token' in data
    assert 'path' not in data  # No raw server paths exposed to the client

    with sqlite3.connect('students.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT kind, stored_name FROM uploads WHERE token = ?", (data['token'],))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == 'profile'

def test_path_injection_in_token_fields_fails(client):
    """Bug test: Submitting .env, ../app.py, or arbitrary paths as tokens must be rejected."""
    form_data = {
        'name': 'Hacker Student',
        'email': 'hacker@example.com',
        'roll_number': 'HACK001',
        'dept_name': 'Security',
        'college_name': 'Test College',
        'trans_id': 'HACK12345',
        'phone': '9876543210',
        'profile_token': '.env',
        'payment_token': '../app.py'
    }
    resp = client.post('/', data=form_data, follow_redirects=False)
    # Must fail validation and NOT redirect
    assert resp.status_code == 200
    assert resp.headers.get('Location') is None
    # Verify .env was not copied to anywhere in static or storage
    import os
    assert not os.path.exists('static/uploads/profiles/HACK001_profile.env')
    assert not os.path.exists('storage/profiles/HACK001_profile.env')

def test_upload_rejects_svg(client):
    """Test: Uploading SVG files must be rejected."""
    import io
    svg_data = io.BytesIO(b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
    resp = client.post('/upload', data={'file': (svg_data, 'malicious.svg'), 'type': 'profile'}, content_type='multipart/form-data')
    assert resp.status_code == 400

def test_upload_rejects_html_renamed_to_png(client):
    """Test: Uploading HTML file disguised as .png must be rejected by image verification."""
    import io
    html_data = io.BytesIO(b'<!DOCTYPE html><html><body><h1>Fake Image</h1></body></html>')
    resp = client.post('/upload', data={'file': (html_data, 'evil.png'), 'type': 'profile'}, content_type='multipart/form-data')
    assert resp.status_code == 400

def test_upload_rejects_oversized_file(client):
    """Test: Uploading file larger than 5 MB must be rejected."""
    import io
    large_data = io.BytesIO(b'0' * (6 * 1024 * 1024))  # 6 MB
    resp = client.post('/upload', data={'file': (large_data, 'huge.png'), 'type': 'profile'}, content_type='multipart/form-data')
    assert resp.status_code in (400, 413)

def test_upload_rejects_decompression_bomb(client, monkeypatch):
    """Test: Decompression bomb must be rejected."""
    import io
    from PIL import Image
    monkeypatch.setattr(Image, 'MAX_IMAGE_PIXELS', 100)  # Very low threshold to trigger bomb
    file_bytes = io.BytesIO()
    img = Image.new('RGB', (50, 50), color='red')  # 2500 pixels > 100
    img.save(file_bytes, 'PNG')
    file_bytes.seek(0)
    resp = client.post('/upload', data={'file': (file_bytes, 'bomb.png'), 'type': 'profile'}, content_type='multipart/form-data')
    assert resp.status_code == 400

def test_old_static_urls_return_404(client):
    """Test: Old unauthenticated URLs for user files must return 404."""
    assert client.get('/uploads/payments/test_payment.jpg').status_code == 404
    assert client.get('/placards/placard_TEST123.jpg').status_code == 404
    assert client.get('/static/placards/placard_TEST123.jpg').status_code == 404
    assert client.get('/static/uploads/payments/test_payment.jpg').status_code == 404

def test_success_page_by_roll_number_returns_404(client):
    """Bug test: Accessing /success/<roll_number> must return 404, only public_token is allowed."""
    assert client.get('/success/CHAR1001').status_code == 404


def test_abuse_localhost_never_blocked():
    """Verify loopback addresses are never locked out."""
    import app as flask_app
    import time
    flask_app.FLAGGED_IPS['127.0.0.1'] = time.time()
    flask_app.FLAGGED_IPS['::1'] = time.time()
    assert flask_app.is_ip_blocked('127.0.0.1') is False
    assert flask_app.is_ip_blocked('::1') is False


def test_abuse_remote_ip_blocked_after_threshold_and_expires(monkeypatch):
    """Verify remote IP is flagged upon reaching threshold and unblocks after cooldown."""
    import app as flask_app
    import time
    ip = '198.51.100.42'
    flask_app.ABUSE_TRACKER[ip] = []
    flask_app.FLAGGED_IPS.pop(ip, None)
    
    # 4 attempts: not yet blocked
    for _ in range(4):
        blocked = flask_app.track_failed_attempt(ip, 'Mozilla', 'test')
        assert blocked is False
    assert flask_app.is_ip_blocked(ip) is False
    
    # 5th attempt: threshold reached
    blocked = flask_app.track_failed_attempt(ip, 'Mozilla', 'test')
    assert blocked is True
    assert flask_app.is_ip_blocked(ip) is True
    
    # Simulate cooldown expiration
    flask_app.FLAGGED_IPS[ip] = time.time() - (flask_app.ABUSE_COOLDOWN_SECONDS + 1)
    assert flask_app.is_ip_blocked(ip) is False








