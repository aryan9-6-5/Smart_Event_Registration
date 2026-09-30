import os
import io
from PIL import Image

def create_in_memory_image():
    file_bytes = io.BytesIO()
    img = Image.new('RGB', (100, 100), color='green')
    img.save(file_bytes, 'PNG')
    file_bytes.seek(0)
    return file_bytes

def test_index_page_loads(client):
    """Characterization test: Index page renders correctly."""
    response = client.get('/')
    assert response.status_code == 200
    assert b"Registration Form" in response.data

def test_file_upload_happy_path(client):
    """Characterization test: POST /upload saves file and returns upload token."""
    data = {
        'file': (create_in_memory_image(), 'test_photo.png'),
        'type': 'profile'
    }
    response = client.post('/upload', data=data, content_type='multipart/form-data')
    assert response.status_code == 200
    json_data = response.get_json()
    assert 'token' in json_data

def test_full_registration_happy_path(client, monkeypatch):
    """Characterization test: Complete registration flow from upload to success page."""
    # 1. Upload profile image
    profile_resp = client.post('/upload', data={
        'file': (create_in_memory_image(), 'profile.png'),
        'type': 'profile'
    }, content_type='multipart/form-data')
    assert profile_resp.status_code == 200
    profile_token = profile_resp.get_json()['token']

    # 2. Upload payment image (mock OCR return value to avoid dependency on tesseract.exe in tests)
    import app
    monkeypatch.setattr(app, 'extract_transaction_id', lambda p: 'TXN12345678')

    payment_resp = client.post('/upload', data={
        'file': (create_in_memory_image(), 'payment.png'),
        'type': 'payment'
    }, content_type='multipart/form-data')
    assert payment_resp.status_code == 200
    payment_token = payment_resp.get_json()['token']

    # 3. Submit registration form
    form_data = {
        'name': 'Char Test Student',
        'email': 'chartest@example.com',
        'roll_number': 'CHAR1001',
        'dept_name': 'CSE',
        'college_name': 'Test College',
        'trans_id': 'TXN12345678',
        'phone': '9876543210',
        'profile_token': profile_token,
        'payment_token': payment_token
    }
    reg_resp = client.post('/', data=form_data, follow_redirects=False)
    assert reg_resp.status_code == 302
    assert '/success/' in reg_resp.headers['Location']


    # 4. Success page loads
    success_resp = client.get('/success/CHAR1001')
    assert success_resp.status_code == 200
    assert b"Registration Successful" in success_resp.data
