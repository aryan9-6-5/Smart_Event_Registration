import os
import uuid
import qrcode
import sqlite3
import smtplib
import secrets
import time
import json
import shutil
import hmac
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from collections import defaultdict
from email.message import EmailMessage
from functools import wraps
from flask import Flask, request, render_template, url_for, jsonify, redirect, abort, send_from_directory, send_file, session
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
from flask_wtf import FlaskForm, CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from wtforms import StringField, EmailField
from wtforms.validators import DataRequired, Email, Length, Regexp
from werkzeug.middleware.proxy_fix import ProxyFix
import pytesseract
from PIL import Image
import re
load_dotenv()

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(24))  # Fallback to random key if not set
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB max upload
ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}
Image.MAX_IMAGE_PIXELS = 25_000_000  # Decompression bomb guard
csrf = CSRFProtect(app)
EMAIL_EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix="email_worker")
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["300 per day", "100 per hour"],
    storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://")
)

def configure_proxy_fix(target_app):
    """Configure ProxyFix middleware when behind a reverse proxy (e.g. Nginx, Cloudflare)."""
    try:
        num_proxies = int(os.getenv('NUM_PROXIES', '0'))
    except ValueError:
        num_proxies = 0

    if num_proxies > 0:
        target_app.wsgi_app = ProxyFix(
            target_app.wsgi_app,
            x_for=num_proxies,
            x_proto=num_proxies,
            x_host=num_proxies,
            x_prefix=num_proxies
        )
        print(f"ProxyFix configured with {num_proxies} trusted proxy hops.")
    return target_app

configure_proxy_fix(app)

@app.before_request
def block_private_file_access():
    if request.path.startswith(('/uploads/', '/placards/', '/tickets/', '/static/uploads/', '/static/placards/', '/static/tickets/')):
        abort(404)

@app.after_request
def set_security_headers(response):
    """Enforce defensive HTTP response headers and Content-Security-Policy."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'"
    )
    return response

@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({'error': 'File size exceeds maximum limit of 5 MB'}), 413

@app.errorhandler(429)
def ratelimit_exceeded(error):
    """Handle rate limit breaches gracefully across API and browser requests."""
    if request.is_json or request.path.startswith(('/upload', '/admin/checkin')):
        return jsonify({'error': 'Rate limit exceeded. Please try again later.'}), 429
    if request.path.startswith('/admin'):
        return render_template('admin_login.html', error="Too many requests. Please wait a moment and try again."), 429
    return render_template('index.html', form=RegistrationForm(), error="Too many requests. Please slow down and try again later."), 429

# Private Storage Configuration (outside static web root)
STORAGE_DIR = os.getenv('STORAGE_DIR', 'storage')
STORAGE_TMP = os.path.join(STORAGE_DIR, 'tmp')
STORAGE_PROFILES = os.path.join(STORAGE_DIR, 'profiles')
STORAGE_PAYMENTS = os.path.join(STORAGE_DIR, 'payments')
STORAGE_PLACARDS = os.path.join(STORAGE_DIR, 'placards')
STORAGE_TICKETS = os.path.join(STORAGE_DIR, 'tickets')

for dir_path in [STORAGE_TMP, STORAGE_PROFILES, STORAGE_PAYMENTS, STORAGE_PLACARDS, STORAGE_TICKETS]:
    os.makedirs(dir_path, exist_ok=True)

# Event Parameters Configuration
CONFIG_PATH = 'event_config.json'
DEFAULT_EVENT_CONFIG = {
    'title': 'College Tech Summit 2024',
    'subtitle': 'OFFICIAL REGISTRATION PASS',
    'description': 'Register now for the biggest technology event of the year!',
    'fee': '₹500',
    'date': 'OCTOBER 24, 2024',
    'ticket_prefix': 'TECH24-',
    'payment_qr': 'images/payment_qr.png'
}

def get_event_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading event config JSON: {e}")
    return DEFAULT_EVENT_CONFIG

@app.context_processor
def inject_event_config():
    config = get_event_config()
    return {
        'event_title': config['title'],
        'event_subtitle': config['subtitle'],
        'event_description': config['description'],
        'registration_fee': config['fee'],
        'event_date': config['date'],
        'ticket_prefix': config['ticket_prefix'],
        'payment_qr': config['payment_qr']
    }

# SMTP Configuration
SMTP_CONFIG = {
    'server': os.getenv('SMTP_SERVER'),
    'port': int(os.getenv('SMTP_PORT')),
    'email': os.getenv('SMTP_EMAIL'),
    'password': os.getenv('SMTP_PASSWORD')
}

# Ensure directories exist
os.makedirs("static/uploads/profiles", exist_ok=True)
os.makedirs("static/uploads/payments", exist_ok=True)
os.makedirs("static/uploads/tmp", exist_ok=True)
os.makedirs("static/placards", exist_ok=True)
os.makedirs("static/tickets", exist_ok=True)

# ─── Abuse Detection System ───────────────────────────────────────────────────
# In-memory tracker: { ip: [timestamp1, timestamp2, ...] }
ABUSE_TRACKER = defaultdict(list)
ABUSE_THRESHOLD = 5          # Max failed attempts before flagging
ABUSE_WINDOW_SECONDS = 900   # 15-minute window
ABUSE_COOLDOWN_SECONDS = 1800  # 30-minute lockout after flagged
# IPs that have been flagged (ip -> flagged_timestamp)
FLAGGED_IPS = {}

def track_failed_attempt(ip, user_agent, form_data_snippet):
    """Track a failed validation attempt. Returns True if abuse threshold exceeded."""
    now = time.time()
    # Clean old entries outside the window
    ABUSE_TRACKER[ip] = [t for t in ABUSE_TRACKER[ip] if now - t < ABUSE_WINDOW_SECONDS]
    ABUSE_TRACKER[ip].append(now)
    
    # Persist to DB
    try:
        with sqlite3.connect('students.db') as conn:
            conn.execute('''INSERT INTO abuse_attempts 
                (ip_address, user_agent, form_data_snippet, created_at)
                VALUES (?, ?, ?, ?)''',
                (ip, user_agent, form_data_snippet, datetime.now().isoformat()))
    except Exception as e:
        print(f"[WARN] Failed to log abuse attempt: {e}")
    
    if len(ABUSE_TRACKER[ip]) >= ABUSE_THRESHOLD:
        FLAGGED_IPS[ip] = now
        return True
    return False

def is_ip_blocked(ip):
    """Check if an IP is currently blocked due to abuse."""
    if ip in FLAGGED_IPS:
        if time.time() - FLAGGED_IPS[ip] < ABUSE_COOLDOWN_SECONDS:
            return True
        else:
            # Cooldown expired, remove flag
            del FLAGGED_IPS[ip]
            ABUSE_TRACKER.pop(ip, None)
    return False

def send_abuse_warning_email(ip, user_agent, form_data):
    """Send a warning email to admin about suspicious activity."""
    try:
        msg = EmailMessage()
        msg['Subject'] = 'SECURITY ALERT: Suspicious Registration Activity Detected'
        msg['From'] = SMTP_CONFIG['email']
        msg['To'] = SMTP_CONFIG['email']  # Send to admin (self)
        msg.set_content(f"""ABUSE DETECTION ALERT
-------------------------------------
Timestamp:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Source IP:   {ip}
User Agent:  {user_agent}

Form Data Submitted:
{form_data}

This IP has exceeded {ABUSE_THRESHOLD} failed validation attempts within {ABUSE_WINDOW_SECONDS // 60} minutes.
The IP has been temporarily blocked for {ABUSE_COOLDOWN_SECONDS // 60} minutes.

-- Smart Event Registration System""")
        
        server = smtplib.SMTP(SMTP_CONFIG['server'], SMTP_CONFIG['port'], timeout=10)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(SMTP_CONFIG['email'], SMTP_CONFIG['password'])
        server.send_message(msg)
        server.quit()
        print(f"[ALERT] Abuse warning email sent for IP: {ip}")
    except Exception as e:
        print(f"[WARN] Failed to send abuse warning email: {e}")

def send_abuse_warning_email_async(ip, user_agent, form_data):
    """Offload abuse warning email to background thread pool."""
    try:
        send_abuse_warning_email(ip, user_agent, form_data)
    except Exception as e:
        print(f"[WARN] Async abuse email task failed: {e}")

# Test profile and payment images
TEST_PROFILE_PATH = "static/uploads/profiles/test_profile.jpg"
TEST_PAYMENT_PATH = "static/uploads/payments/test_payment.jpg"

def configure_tesseract():
    """Discover or configure the Tesseract OCR binary path across platforms."""
    env_cmd = os.getenv('TESSERACT_CMD')
    if env_cmd and os.path.exists(env_cmd):
        pytesseract.pytesseract.tesseract_cmd = env_cmd
        return env_cmd
    discovered = shutil.which('tesseract')
    if discovered:
        pytesseract.pytesseract.tesseract_cmd = discovered
        return discovered
    default_win = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    if os.path.exists(default_win):
        pytesseract.pytesseract.tesseract_cmd = default_win
        return default_win
    print("[WARN] Tesseract OCR binary not found. OCR features will fail gracefully.")
    return None

TESSERACT_CMD = configure_tesseract()

def extract_transaction_id(image_path):
    """Return (candidate, confident). Only a 12-digit UPI UTR is 'confident' (auto-trustable)."""
    try:
        text = pytesseract.image_to_string(Image.open(image_path))

        labelled_utr = r"(?:txn[^\w]?id|Transaction[^\w]*ID|UPI[^\w]*(?:Ref|Transaction)[^\w]*(?:ID|No)?|UTR)[^\w]*(\d{12})\b"
        for pattern in (labelled_utr, r"\b(\d{12})\b"):
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1), True

        # Loose fallbacks are never trusted: caller must route these to manual review
        fallbacks = [
            r"(?:txn[^\w]?id|Transaction[^\w]*ID|UPI[^\w]*Ref|UTR)[^\w]?:?\s*([A-Za-z0-9]{6,50})",
            r"\b([A-Za-z0-9]{8,25})\b"
        ]
        for pattern in fallbacks:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(), False

    except Exception as e:
        print("OCR error:", e)

    return None, False

def compute_image_phash(image_path):
    """Compute 64-bit difference hash (dHash) string using Pillow."""
    try:
        with Image.open(image_path) as img:
            resized = img.convert('L').resize((9, 8), Image.Resampling.LANCZOS)
            diff = []
            for row in range(8):
                for col in range(8):
                    diff.append('1' if resized.getpixel((col, row)) > resized.getpixel((col + 1, row)) else '0')
            decimal_val = int(''.join(diff), 2)
            return f"{decimal_val:016x}"
    except Exception as e:
        print(f"Error computing phash for {image_path}: {e}")
        return None

def hamming_distance(hash1_hex, hash2_hex):
    """Calculate bitwise Hamming distance between two 16-hex-character hashes."""
    if not hash1_hex or not hash2_hex:
        return 64
    try:
        val1 = int(hash1_hex, 16)
        val2 = int(hash2_hex, 16)
        return (val1 ^ val2).bit_count()
    except Exception:
        return 64

def sign_ticket(ticket_id, ticket_secret=None):
    """Cryptographically sign a ticket ID using HMAC-SHA256."""
    server_key = app.config.get('SECRET_KEY', 'default-key')
    combined_key = f"{server_key}:{ticket_secret or ''}".encode()
    sig = hmac.new(combined_key, ticket_id.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{ticket_id}.{sig}"

def verify_ticket_signature(qr_payload, ticket_secret=None):
    """Verify cryptographic signature on a scanned QR payload."""
    if not qr_payload or '.' not in qr_payload:
        return False, None
    ticket_id, provided_sig = qr_payload.rsplit('.', 1)
    expected_payload = sign_ticket(ticket_id, ticket_secret)
    expected_sig = expected_payload.rsplit('.', 1)[1]
    if hmac.compare_digest(provided_sig, expected_sig):
        return True, ticket_id
    return False, None

# Create test images if they don't exist
def ensure_test_images():
    if not os.path.exists(TEST_PROFILE_PATH):
        img = Image.new('RGB', (300, 300), color='blue')
        draw = ImageDraw.Draw(img)
        draw.text((100, 150), "TEST", fill="white")
        img.save(TEST_PROFILE_PATH)
    
    if not os.path.exists(TEST_PAYMENT_PATH):
        img = Image.new('RGB', (300, 300), color='green')
        draw = ImageDraw.Draw(img)
        draw.text((100, 150), "PAYMENT", fill="white")
        img.save(TEST_PAYMENT_PATH)

class RegistrationForm(FlaskForm):
    name = StringField('Name', validators=[
        DataRequired(message="Full name is required."),
        Length(min=2, max=100, message="Name must be between 2 and 100 characters.")
    ])
    email = EmailField('Email', validators=[
        DataRequired(message="Email address is required."),
        Email(message="Please enter a valid email address (e.g. name@example.com).")
    ])
    roll_number = StringField('Roll Number', validators=[
        DataRequired(message="Roll number is required."),
        Length(min=2, max=20, message="Roll number must be between 2 and 20 characters."),
        Regexp(r'^[A-Za-z0-9_-]+$', message="Roll number may only contain letters, digits, hyphen and underscore.")
    ])
    dept_name = StringField('Department', validators=[
        DataRequired(message="Department name is required."),
        Length(max=100, message="Department name cannot exceed 100 characters.")
    ])
    college_name = StringField('College', validators=[
        DataRequired(message="College name is required."),
        Length(max=100, message="College name cannot exceed 100 characters.")
    ])
    trans_id = StringField('Transaction ID', validators=[
        DataRequired(message="Transaction ID is required. Upload payment proof first."),
        Length(min=5, max=50, message="Transaction ID must be between 5 and 50 characters."),
        Regexp(r'^[A-Za-z0-9]{5,50}$', message="Transaction ID must be alphanumeric and between 5 and 50 characters.")
    ])
    phone = StringField('Phone', validators=[
        DataRequired(message="Phone number is required."),
        Regexp(r'^\d{10}$', message="Phone number must be exactly 10 digits. No spaces, dashes, or country codes.")
    ])
    profile_token = StringField('Profile Token', validators=[
        DataRequired(message="Profile photo is required. Please upload your photo.")
    ])
    payment_token = StringField('Payment Token', validators=[
        DataRequired(message="Payment proof is required. Please upload your payment screenshot.")
    ])

# Test data for quick testing
TEST_DATA = {
    "name": "test",
    "email": "xepek94185@hikuhu.com",
    "roll_number": "TEST123",
    "dept_name": "Computer Science",
    "college_name": "Test University",
    "trans_id": "TEST12345",
    "phone": "9876543210",
    "profile_path": TEST_PROFILE_PATH,
    "payment_path": TEST_PAYMENT_PATH
}

def init_db():
    # Clear intermediate/temp uploads folder on server start
    if os.path.exists(STORAGE_TMP):
        try:
            for f in os.listdir(STORAGE_TMP):
                file_path = os.path.join(STORAGE_TMP, f)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            print("Temporary upload folder cleared on startup.")
        except Exception as e:
            print(f"Error cleaning tmp dir: {e}")

    with sqlite3.connect('students.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, email TEXT, roll_number TEXT UNIQUE,
            dept_name TEXT, college_name TEXT, trans_id TEXT UNIQUE,
            phone TEXT, profile_path TEXT, payment_path TEXT,
            placard_path TEXT, public_token TEXT UNIQUE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'CONFIRMED',
            ocr_trans_id TEXT,
            trans_id_source TEXT DEFAULT 'manual',
            payment_phash TEXT,
            email_status TEXT DEFAULT 'pending',
            checked_in_at TIMESTAMP,
            ticket_secret TEXT
        )''')
        
        # Additive migration: check and add missing columns
        cursor.execute("PRAGMA table_info(students)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'created_at' not in columns:
            try:
                cursor.execute("ALTER TABLE students ADD COLUMN created_at TIMESTAMP DEFAULT '2026-06-24 00:00:00'")
                conn.commit()
                print("Added missing created_at column to students table.")
            except Exception as e:
                print(f"Error adding created_at column: {e}")

        additive_columns = [
            ('public_token', "TEXT", "CREATE UNIQUE INDEX IF NOT EXISTS idx_students_public_token ON students(public_token)"),
            ('status', "TEXT DEFAULT 'CONFIRMED'", "CREATE INDEX IF NOT EXISTS idx_students_status ON students(status)"),
            ('ocr_trans_id', "TEXT", None),
            ('trans_id_source', "TEXT DEFAULT 'manual'", None),
            ('payment_phash', "TEXT", "CREATE INDEX IF NOT EXISTS idx_students_phash ON students(payment_phash)"),
            ('email_status', "TEXT DEFAULT 'pending'", None),
            ('checked_in_at', "TIMESTAMP", None),
            ('ticket_secret', "TEXT", None)
        ]

        for col_name, col_def, idx_sql in additive_columns:
            if col_name not in columns:
                try:
                    cursor.execute(f"ALTER TABLE students ADD COLUMN {col_name} {col_def}")
                    if idx_sql:
                        cursor.execute(idx_sql)
                    conn.commit()
                    print(f"Added missing {col_name} column to students table.")
                except Exception as e:
                    print(f"Error adding {col_name} column: {e}")


        cursor.execute('''CREATE TABLE IF NOT EXISTS abuse_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_address TEXT NOT NULL,
            user_agent TEXT,
            form_data_snippet TEXT,
            created_at TEXT NOT NULL
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS uploads (
            token TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            stored_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ocr_trans_id TEXT,
            payment_phash TEXT
        )''')

        cursor.execute("PRAGMA table_info(uploads)")
        upload_cols = [row[1] for row in cursor.fetchall()]
        if 'payment_phash' not in upload_cols:
            try:
                cursor.execute("ALTER TABLE uploads ADD COLUMN payment_phash TEXT")
                conn.commit()
            except Exception as e:
                print(f"Error adding payment_phash to uploads: {e}")

# def generate_placard(name, roll, dept, college, phone, profile_path):
#     placard = Image.new('RGB', (1200, 800), '#ffffff')
#     draw = ImageDraw.Draw(placard)

#     try:
#         title_font = ImageFont.truetype('static/fonts/Poppins-Bold.ttf', 48)
#         header_font = ImageFont.truetype('static/fonts/Poppins-SemiBold.ttf', 36)
#         text_font = ImageFont.truetype('static/fonts/Poppins-Regular.ttf', 32)
#     except IOError:
#         print("Font loading error - using default font")
#         title_font = header_font = text_font = ImageFont.load_default()

#     draw.rectangle([(0, 0), (1200, 120)], fill='#1a237e')
#     draw.text((600, 60), "College Tech Summit 2024", fill='#ffffff', font=title_font, anchor='mm')

#     try:
#         profile = Image.open(profile_path).convert('RGB')
#         profile.thumbnail((300, 300), Image.Resampling.LANCZOS)
#         placard.paste(profile, (50, 150))
#     except Exception as e:
#         print(f"Error loading profile image: {e}")
#         # Create a placeholder image
#         placeholder = Image.new('RGB', (300, 300), color='gray')
#         draw_p = ImageDraw.Draw(placeholder)
#         draw_p.text((150, 150), "No Image", fill="white", anchor='mm')
#         placard.paste(placeholder, (50, 150))

#     details = [("Name", name), ("Roll Number", roll), ("Department", dept), 
#               ("College", college), ("Phone", phone)]
#     y_offset = 180
#     for label, value in details:
#         draw.text((400, y_offset), f"{label}:", fill='#1a237e', font=header_font)
#         draw.text((550, y_offset), value, fill='#1a237e', font=text_font)
#         y_offset += 60

#     # Generate and save QR code
#     qr_data = f"TECH24-{roll}"
#     qr_img = qrcode.make(qr_data)
#     qr_path = f"static/tickets/ticket_{roll}.png"
#     qr_img.save(qr_path)
    
#     # Resize and paste QR code
#     qr = Image.open(qr_path).resize((250, 250), Image.Resampling.LANCZOS)
#     placard.paste(qr, (850, 500))

#     draw.rectangle([(0, 750), (1200, 800)], fill='#1a237e')
#     draw.text((600, 775), "Bring this placard to the event for entry", 
#              fill='#ffffff', font=text_font, anchor='mm')

#     placard_path = f"static/placards/placard_{roll}.jpg"
#     placard.save(placard_path)
#     return placard_path

def generate_placard(name, roll, dept, college, phone, profile_path, ticket_secret=None):
    config = get_event_config()
    # Define theme colors matching the user's CSS variables
    COLOR_PRIMARY = '#1A2A45'       # Rich navy blue for primary text
    COLOR_SECONDARY = '#94A3B8'     # Muted slate blue for labels
    COLOR_BG_LIGHT = '#F8FAFC'      # Soft off-white background
    COLOR_SOFT_BG = '#E6EDF5'       # Ultra-light blue-gray for borders/badges
    COLOR_TEXT_DARK = '#1E293B'     # Deep charcoal for body values
    COLOR_WHITE = '#FFFFFF'         # Pure white for stub background

    # Helper function to load Poppins fonts with fallbacks
    def load_poppins_font(font_type, size):
        possible_paths = [
            f"fonts/Poppins-{font_type}.ttf",
            f"static/fonts/Poppins-{font_type}.ttf",
            f"../fonts/Poppins-{font_type}.ttf",
            f"../../fonts/Poppins-{font_type}.ttf"
        ]
        for path in possible_paths:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception as e:
                    print(f"Error loading font from {path}: {e}")
        return ImageFont.load_default()

    # Load Poppins fonts at target sizes
    font_title = load_poppins_font('Bold', 26)
    font_subtitle = load_poppins_font('Medium', 13)
    font_label = load_poppins_font('SemiBold', 12)
    font_name = load_poppins_font('SemiBold', 22)
    font_value = load_poppins_font('Medium', 17)
    font_badge = load_poppins_font('Bold', 13)
    font_footer = load_poppins_font('Regular', 12)

    # Create main canvas (1000x600 px)
    placard = Image.new('RGB', (1000, 600), COLOR_BG_LIGHT)
    draw = ImageDraw.Draw(placard)

    # 1. Asymmetric Split: Solid white stub background for the right 30% (width 300px)
    draw.rectangle([(700, 0), (1000, 600)], fill=COLOR_WHITE)

    # 2. Outer Frame: 1px border around the entire canvas
    draw.rectangle([(0, 0), (999, 599)], outline=COLOR_SOFT_BG, width=1)

    # 3. Ticket Divider: 2px dashed vertical perforation line at x = 700
    dash_length = 8
    gap_length = 8
    for y in range(0, 600, dash_length + gap_length):
        draw.line([(700, y), (700, min(y + dash_length, 600))], fill=COLOR_SOFT_BG, width=2)

    # 4. Draw Left Section Header (Title & Subtitle)
    draw.text((50, 45), config['title'].upper(), fill=COLOR_PRIMARY, font=font_title)
    draw.text((50, 85), config['subtitle'].upper(), fill=COLOR_SECONDARY, font=font_subtitle)
    
    # Divider line below header
    draw.line([(50, 120), (650, 120)], fill=COLOR_SOFT_BG, width=1)

    # 5. Load and paste profile image (220x220) with rounded corners and thin border
    profile_size = (220, 220)
    profile_pos = (50, 160)

    try:
        profile = Image.open(profile_path).convert('RGB')
        profile = profile.resize(profile_size, Image.Resampling.LANCZOS)
        
        # Round the corners using a mask
        mask = Image.new('L', profile_size, 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([(0, 0), profile_size], radius=24, fill=255)
        
        placard.paste(profile, profile_pos, mask=mask)
    except Exception as e:
        print(f"[WARN] Error loading profile image: {e}")
        # Draw placeholder
        placeholder = Image.new('RGB', profile_size, color=COLOR_SOFT_BG)
        draw_placeholder = ImageDraw.Draw(placeholder)
        draw_placeholder.text((110, 110), "NO PHOTO", fill=COLOR_PRIMARY, font=font_badge, anchor='mm')
        
        mask = Image.new('L', profile_size, 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([(0, 0), profile_size], radius=24, fill=255)
        
        placard.paste(placeholder, profile_pos, mask=mask)

    # Draw the crisp, thin border around the profile image
    draw.rounded_rectangle([profile_pos, (profile_pos[0] + profile_size[0], profile_pos[1] + profile_size[1])], 
                           radius=24, outline=COLOR_SOFT_BG, width=1)

    # 6. Student Details: Modern stacked layout
    # NAME
    draw.text((310, 160), "NAME", fill=COLOR_SECONDARY, font=font_label)
    draw.text((310, 180), name, fill=COLOR_PRIMARY, font=font_name)

    # ROLL NUMBER
    draw.text((310, 240), "ROLL NUMBER", fill=COLOR_SECONDARY, font=font_label)
    draw.text((310, 260), roll, fill=COLOR_TEXT_DARK, font=font_value)

    # DEPARTMENT
    draw.text((310, 320), "DEPARTMENT", fill=COLOR_SECONDARY, font=font_label)
    draw.text((310, 340), dept, fill=COLOR_TEXT_DARK, font=font_value)

    # PHONE NUMBER
    draw.text((500, 320), "PHONE NUMBER", fill=COLOR_SECONDARY, font=font_label)
    draw.text((500, 340), phone, fill=COLOR_TEXT_DARK, font=font_value)

    # COLLEGE
    draw.text((310, 400), "COLLEGE", fill=COLOR_SECONDARY, font=font_label)
    draw.text((310, 420), college, fill=COLOR_TEXT_DARK, font=font_value)

    # Footer (Left side)
    draw.text((50, 530), "Bring this placard to the event for entry", fill=COLOR_SECONDARY, font=font_footer)

    # 7. Right Stub Elements
    # Attendee Pill Badge
    draw.rounded_rectangle([(770, 70), (930, 110)], radius=20, fill=COLOR_SOFT_BG)
    draw.text((850, 90), "ATTENDEE", fill=COLOR_PRIMARY, font=font_badge, anchor='mm')

    # QR Code generation with cryptographic signature
    ticket_id = f"{config['ticket_prefix']}{roll}"
    qr_data = sign_ticket(ticket_id, ticket_secret=ticket_secret)
    qr_img = qrcode.make(qr_data)
    qr_path = os.path.join(STORAGE_TICKETS, f"ticket_{roll}.png")
    os.makedirs(os.path.dirname(qr_path), exist_ok=True)
    qr_img.save(qr_path)

    qr = Image.open(qr_path).resize((200, 200), Image.Resampling.LANCZOS)
    placard.paste(qr, (750, 180))

    # Ticket ID below QR
    draw.text((850, 420), "TICKET ID", fill=COLOR_SECONDARY, font=font_label, anchor='mm')
    draw.text((850, 445), f"{config['ticket_prefix']}{roll}", fill=COLOR_PRIMARY, font=font_value, anchor='mm')

    # Date info at bottom of the stub
    draw.text((850, 530), config['date'].upper(), fill=COLOR_SECONDARY, font=font_footer, anchor='mm')

    placard_path = os.path.join(STORAGE_PLACARDS, f"placard_{roll}.jpg")
    os.makedirs(os.path.dirname(placard_path), exist_ok=True)
    placard.save(placard_path)
    return placard_path


def send_email(to_email, placard_path):
    msg = EmailMessage()
    msg['Subject'] = 'College Tech Summit 2024 Registration Confirmation'
    msg['From'] = SMTP_CONFIG['email']
    msg['To'] = to_email
    msg.set_content('Your registration is confirmed! Find your ticket attached.')

    try:
        with open(placard_path, 'rb') as f:
            msg.add_attachment(f.read(), maintype='image', subtype='jpeg', filename='placard.jpg')
    except Exception as e:
        print(f"Error attaching placard: {e}")
        # Continue with email sending even if attachment fails

    try:
        print(f"Connecting to {SMTP_CONFIG['server']}:{SMTP_CONFIG['port']}")
        server = smtplib.SMTP(SMTP_CONFIG['server'], SMTP_CONFIG['port'], timeout=10)
        server.set_debuglevel(1)  # Enable debug output
        server.ehlo()  # Identify to server
        server.starttls()  # Start TLS encryption
        server.ehlo()  # Re-identify after STARTTLS
        print(f"Logging in with {SMTP_CONFIG['email']}")
        server.login(SMTP_CONFIG['email'], SMTP_CONFIG['password'])
        server.send_message(msg)
        server.quit()
        print("Email sent successfully")
        return True
    except Exception as e:
        print(f"SMTP error: {str(e)}")
        return False

def send_email_async(student_id, to_email, placard_path):
    """Background worker task to deliver attendee placard email and update email_status."""
    success = False
    try:
        success = bool(send_email(to_email, placard_path))
    except Exception as e:
        print(f"Error in send_email_async: {e}")
        success = False

    try:
        with sqlite3.connect('students.db', timeout=10) as conn:
            status_val = 'sent' if success else 'failed'
            conn.execute("UPDATE students SET email_status = ? WHERE id = ?", (status_val, student_id))
    except Exception as e:
        print(f"Error updating student email_status in DB: {e}")

    return success

def cleanup_old_temp_files(max_age_seconds=1800):  # 30 minutes
    if os.path.exists(STORAGE_TMP):
        try:
            now = time.time()
            for f in os.listdir(STORAGE_TMP):
                file_path = os.path.join(STORAGE_TMP, f)
                if os.path.isfile(file_path):
                    if now - os.path.getmtime(file_path) > max_age_seconds:
                        os.remove(file_path)
            print("Cleanup of older temporary upload files completed.")
        except Exception as e:
            print(f"Error cleaning old temp files: {e}")

@app.route('/upload', methods=['POST'])
@limiter.limit("15 per minute")
def upload_file():
    cleanup_old_temp_files()
    print("Upload endpoint called")
    print(f"Request files: {list(request.files.keys())}")
    print(f"Request form: {list(request.form.keys())}")
    
    if 'file' not in request.files:
        print("Error: No file part in request")
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    print(f"File info: name={file.filename}, content_type={file.content_type}")
    
    if file.filename == '':
        print("Error: Empty filename")
        return jsonify({'error': 'No selected file'}), 400
    
    # Determine upload type
    upload_type = request.form.get('type', 'profile')
    print(f"Upload type from form: {upload_type}")
    
    if upload_type in ['profile', 'profiles']:
        kind = 'profile'
    elif upload_type in ['payment', 'payments']:
        kind = 'payment'
    else:
        kind = 'profile'  # fallback

    # Validate extension whitelist
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({'error': 'Invalid file type. Allowed formats: PNG, JPG, JPEG, WEBP.'}), 400

    # Generate random upload token
    token = uuid.uuid4().hex

    # Validate image data with Pillow verify()
    try:
        img = Image.open(file.stream)
        img.verify()
    except Image.DecompressionBombError:
        return jsonify({'error': 'Image exceeds maximum allowable pixel dimensions.'}), 400
    except Exception:
        return jsonify({'error': 'Invalid or corrupted image file.'}), 400

    # Rewind stream, re-open, and re-encode to sanitize image
    file.stream.seek(0)
    try:
        img = Image.open(file.stream)
        target_ext = '.png' if ext == '.png' else '.jpg'
        filename = f"{token}{target_ext}"
        filepath = os.path.join(STORAGE_TMP, filename)
        
        os.makedirs(STORAGE_TMP, exist_ok=True)
        if target_ext == '.jpg':
            img = img.convert('RGB')
            img.save(filepath, 'JPEG', quality=90)
        else:
            img.save(filepath, 'PNG')
        print(f"File sanitized and saved to temp: {filepath}")
    except Image.DecompressionBombError:
        return jsonify({'error': 'Image exceeds maximum allowable pixel dimensions.'}), 400
    except Exception as e:
        return jsonify({'error': f'Failed to process image: {str(e)}'}), 400

    try:
        trans_id = None
        payment_phash = None
        # OCR and perceptual hash only for payment screenshots
        if kind == 'payment':
            candidate, confident = extract_transaction_id(filepath)
            trans_id = candidate if confident else None  # only trusted OCR results are stored
            payment_phash = compute_image_phash(filepath)
            print(f"OCR extracted Transaction ID: {trans_id}, phash: {payment_phash}")

        with sqlite3.connect('students.db') as conn:
            conn.execute('''
                INSERT INTO uploads (token, kind, stored_name, ocr_trans_id, payment_phash)
                VALUES (?, ?, ?, ?, ?)
            ''', (token, kind, filename, trans_id, payment_phash))

        response_data = {
            'message': 'File uploaded successfully',
            'token': token
        }
        if kind == 'payment':
            response_data['trans_id'] = trans_id or ""

        return jsonify(response_data), 200

    except Exception as e:
        error_msg = f"Failed to record upload: {str(e)}"
        print(error_msg)
        return jsonify({'error': error_msg}), 500


@app.route('/placard/<public_token>', methods=['GET'])
def view_placard(public_token):
    """Serve student placard image safely via unguessable public_token."""
    with sqlite3.connect('students.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT placard_path FROM students WHERE public_token = ?", (public_token,))
        row = cursor.fetchone()
        if not row:
            abort(404)
        placard_path = row[0]
        if not os.path.exists(placard_path):
            abort(404)
        return send_file(os.path.abspath(placard_path), mimetype='image/jpeg')

@app.route('/success/<public_token>', methods=['GET'])
def success_page(public_token):
    """Dedicated GET route for the success page using unguessable public_token."""
    with sqlite3.connect('students.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT roll_number, placard_path FROM students WHERE public_token = ?", (public_token,))
        row = cursor.fetchone()
        if not row:
            abort(404)
        placard_path = row[1]
        if not os.path.exists(placard_path):
            abort(404)

    email_failed = request.args.get('email_failed') == '1'
    return render_template('success.html', 
        placard_url=url_for('view_placard', public_token=public_token),
        email_failed=email_failed)

# ─── Admin Portal ─────────────────────────────────────────────────────────────
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')

def safe_next_url(target):
    """Allow only same-site relative paths as post-login redirect targets."""
    if target and target.startswith('/') and not target.startswith('//') and '\\' not in target:
        return target
    return None

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login', next=request.full_path.rstrip('?')))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/admin/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(safe_next_url(request.args.get('next')) or url_for('admin_dashboard'))
        return render_template('admin_login.html', error="Invalid credentials"), 200
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/admin', methods=['GET'])
@admin_required
def admin_dashboard():
    q = request.args.get('q', '').strip()
    with sqlite3.connect('students.db') as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # Pending students awaiting verification
        cur.execute('''
            SELECT id, name, roll_number, email, phone, trans_id, ocr_trans_id, trans_id_source, created_at
            FROM students
            WHERE status = 'PENDING'
            ORDER BY id DESC
        ''')
        pending_students = cur.fetchall()

        # Search results if query provided
        search_results = []
        if q:
            cur.execute('''
                SELECT id, name, roll_number, email, phone, trans_id, status, checked_in_at, created_at
                FROM students
                WHERE roll_number LIKE ? OR name LIKE ? OR trans_id LIKE ?
                ORDER BY id DESC
            ''', (f"%{q}%", f"%{q}%", f"%{q}%"))
            search_results = cur.fetchall()

    return render_template('admin_dashboard.html', 
        pending_students=pending_students,
        search_results=search_results,
        q=q)

@app.route('/admin/approve/<int:student_id>', methods=['POST'])
@admin_required
def admin_approve(student_id):
    with sqlite3.connect('students.db') as conn:
        conn.execute("UPDATE students SET status = 'CONFIRMED' WHERE id = ?", (student_id,))
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/reject/<int:student_id>', methods=['POST'])
@admin_required
def admin_reject(student_id):
    with sqlite3.connect('students.db') as conn:
        conn.execute("UPDATE students SET status = 'REJECTED' WHERE id = ?", (student_id,))
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/payment_proof/<int:student_id>', methods=['GET'])
@admin_required
def admin_payment_proof(student_id):
    with sqlite3.connect('students.db') as conn:
        cur = conn.cursor()
        cur.execute("SELECT payment_path FROM students WHERE id = ?", (student_id,))
        row = cur.fetchone()
        if not row or not row[0] or not os.path.exists(row[0]):
            abort(404)
        return send_file(os.path.abspath(row[0]))

@app.route('/admin/checkin', methods=['GET', 'POST'])
@limiter.exempt  # gate scanners must never be throttled; access is already admin-authenticated
@admin_required
def admin_checkin():
    if request.method == 'GET':
        return render_template('admin_checkin.html')

    qr_payload = None
    if request.is_json:
        qr_payload = (request.json.get('qr_payload') or '').strip()
    else:
        qr_payload = (request.form.get('qr_payload') or '').strip()

    if not qr_payload:
        return jsonify({'status': 'error', 'message': 'Missing QR payload'}), 400

    if '.' not in qr_payload:
        return jsonify({'status': 'error', 'message': 'Invalid QR payload format'}), 400

    ticket_id = qr_payload.rsplit('.', 1)[0]
    config = get_event_config()
    ticket_prefix = config.get('ticket_prefix', 'TECH24-')

    if ticket_id.startswith(ticket_prefix):
        roll_number = ticket_id[len(ticket_prefix):].strip()
    else:
        roll_number = ticket_id.strip()

    with sqlite3.connect('students.db') as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute('''
            SELECT id, name, roll_number, dept_name, college_name, status, checked_in_at, ticket_secret
            FROM students
            WHERE roll_number = ?
        ''', (roll_number.upper(),))
        student = cur.fetchone()

        if not student:
            return jsonify({'status': 'error', 'message': 'Ticket ID not found in registration database'}), 404

        # 1. Cryptographic signature verification
        is_valid, _ = verify_ticket_signature(qr_payload, ticket_secret=student['ticket_secret'])
        if not is_valid:
            return jsonify({'status': 'error', 'message': 'FORGERY DETECTED: Invalid cryptographic signature!'}), 400

        # 2. Registration status gate
        if student['status'] != 'CONFIRMED':
            return jsonify({
                'status': 'error',
                'message': f"Entry Denied: Registration status is {student['status']} (requires CONFIRMED)."
            }), 403

        # 3. Check if already checked in
        if student['checked_in_at']:
            return jsonify({
                'status': 'already_checked_in',
                'message': f"ALREADY USED: Checked in earlier at {student['checked_in_at']}",
                'student': {
                    'name': student['name'],
                    'roll_number': student['roll_number'],
                    'dept_name': student['dept_name'],
                    'college_name': student['college_name'],
                    'checked_in_at': student['checked_in_at']
                }
            }), 409

        # 4. Atomic idempotent update
        now_ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cur.execute("UPDATE students SET checked_in_at = ? WHERE id = ? AND checked_in_at IS NULL", (now_ts, student['id']))
        if cur.rowcount == 0:
            return jsonify({
                'status': 'already_checked_in',
                'message': 'ALREADY USED: Checked in by another gate scanner',
                'student': {
                    'name': student['name'],
                    'roll_number': student['roll_number']
                }
            }), 409

        return jsonify({
            'status': 'success',
            'message': f"Check-in verified! Welcome, {student['name']}!",
            'student': {
                'name': student['name'],
                'roll_number': student['roll_number'],
                'dept_name': student['dept_name'],
                'college_name': student['college_name'],
                'checked_in_at': now_ts
            }
        }), 200


@app.route('/', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])
def index():
    cleanup_old_temp_files()
    form = RegistrationForm()

    # ─── Abuse Detection Gate ─────────────────────────────────────────────
    client_ip = request.remote_addr or 'unknown'
    if is_ip_blocked(client_ip):
        return render_template('index.html', form=form, 
            error="Suspicious activity detected from your connection. We've noticed repeated invalid submissions from your credentials. Your access has been temporarily restricted. This incident has been reported.",
            abuse_blocked=True)

    if not form.validate_on_submit():
        print("[ERROR] Form validation failed")
        print("Form errors:", form.errors)
        
        # ─── Track failed attempt for abuse detection ────────────────────
        if request.method == 'POST':
            form_snippet = f"name={request.form.get('name','')}, roll={request.form.get('roll_number','')}, phone={request.form.get('phone','')}, email={request.form.get('email','')}"
            user_agent = request.headers.get('User-Agent', 'unknown')
            is_abusive = track_failed_attempt(client_ip, user_agent, form_snippet)
            
            if is_abusive:
                print(f"[ALERT] ABUSE DETECTED from IP: {client_ip}")
                EMAIL_EXECUTOR.submit(send_abuse_warning_email_async, client_ip, user_agent, form_snippet)
                return render_template('index.html', form=form,
                    error="Suspicious activity detected from your connection. We've seen repeated invalid submissions from your credentials. This incident has been reported.",
                    abuse_blocked=True)
            
            # Show a banner to the user that validation failed
            return render_template('index.html', form=form, error="Form validation failed. Please correct the highlighted fields below.")

    elif form.validate_on_submit():
        print("Form submitted with data:", {field.name: field.data for field in form})
        print("[OK] form.validate_on_submit passed")
        try:
            profile_token = (form.profile_token.data or '').strip()
            payment_token = (form.payment_token.data or '').strip()
            
            # ─── Server-side token resolution via uploads table ──────────
            with sqlite3.connect('students.db') as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT stored_name FROM uploads WHERE token = ? AND kind = 'profile'", (profile_token,))
                row_prof = cursor.fetchone()
                if not row_prof:
                    return render_template('index.html', form=form, error="Profile photo upload is invalid or expired. Please re-upload.")
                
                cursor.execute("SELECT stored_name, ocr_trans_id, payment_phash FROM uploads WHERE token = ? AND kind = 'payment'", (payment_token,))
                row_pay = cursor.fetchone()
                if not row_pay:
                    return render_template('index.html', form=form, error="Payment proof upload is invalid or expired. Please re-upload.")
            
            stored_profile = row_prof[0]
            stored_payment = row_pay[0]
            ocr_trans_id = row_pay[1]
            payment_phash = row_pay[2]

            profile_tmp_path = os.path.join(STORAGE_TMP, stored_profile)
            payment_tmp_path = os.path.join(STORAGE_TMP, stored_payment)
            
            if not os.path.exists(profile_tmp_path):
                return render_template('index.html', form=form, error="Profile photo file is missing. Please re-upload.")
            if not os.path.exists(payment_tmp_path):
                return render_template('index.html', form=form, error="Payment proof file is missing. Please re-upload.")

            # Compute phash if not already computed
            if not payment_phash and os.path.exists(payment_tmp_path):
                payment_phash = compute_image_phash(payment_tmp_path)

            # Check for duplicate payment screenshot across registered students
            is_duplicate_payment = False
            if payment_phash:
                with sqlite3.connect('students.db') as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT id, payment_phash FROM students WHERE payment_phash IS NOT NULL")
                    for prev_id, prev_hash in cur.fetchall():
                        if hamming_distance(payment_phash, prev_hash) <= 4:
                            is_duplicate_payment = True
                            print(f"[WARN] Duplicate payment proof detected matching student id={prev_id}")
                            break

            if is_duplicate_payment:
                # Force to PENDING review even if OCR was valid
                final_trans_id = ocr_trans_id.strip() if (ocr_trans_id and ocr_trans_id.strip()) else form.trans_id.data.strip()
                trans_id_source = 'ocr' if (ocr_trans_id and ocr_trans_id.strip()) else 'manual'
                student_status = 'PENDING'
            elif ocr_trans_id and ocr_trans_id.strip():
                final_trans_id = ocr_trans_id.strip()
                trans_id_source = 'ocr'
                student_status = 'CONFIRMED'
            else:
                final_trans_id = form.trans_id.data.strip()
                trans_id_source = 'manual'
                student_status = 'PENDING'
            
            # Destination files in private storage
            roll_number_clean = form.roll_number.data.strip().upper()
            profile_ext = os.path.splitext(stored_profile)[1] or ".png"
            payment_ext = os.path.splitext(stored_payment)[1] or ".png"
            
            final_profile_path = os.path.join(STORAGE_PROFILES, f"{roll_number_clean}_profile{profile_ext}")
            final_payment_path = os.path.join(STORAGE_PAYMENTS, f"{roll_number_clean}_payment{payment_ext}")
            
            # Generate unguessable public token and unique ticket secret for attendee
            public_token = uuid.uuid4().hex
            ticket_secret = secrets.token_hex(16)

            # 1. Atomic reservation via single transaction INSERT
            try:
                with sqlite3.connect('students.db', timeout=10) as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO students 
                        (name, email, roll_number, dept_name, college_name, 
                         trans_id, phone, profile_path, payment_path, placard_path, public_token,
                         status, ocr_trans_id, trans_id_source, payment_phash, ticket_secret)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ''', (
                        form.name.data, form.email.data, roll_number_clean,
                        form.dept_name.data, form.college_name.data,
                        final_trans_id, form.phone.data,
                        final_profile_path, final_payment_path, None,
                        public_token,
                        student_status, ocr_trans_id, trans_id_source, payment_phash, ticket_secret
                    ))
                    student_id = cursor.lastrowid
            except sqlite3.IntegrityError as e:
                err_str = str(e).lower()
                if "roll_number" in err_str:
                    return render_template('index.html', form=form, error="This roll number is already registered. Each student can only register once.")
                elif "trans_id" in err_str:
                    return render_template('index.html', form=form, error="This Transaction ID has already been used. Each payment can only be used for one registration.")
                return render_template('index.html', form=form, error="A registration conflict occurred. Please check your details.")

            placard_path = None
            try:
                # 2. Generate placard using the temp profile photo and signed QR code
                placard_path = generate_placard(
                    form.name.data,
                    roll_number_clean,
                    form.dept_name.data,
                    form.college_name.data,
                    form.phone.data,
                    profile_tmp_path,
                    ticket_secret=ticket_secret
                )
                
                # 3. Update placard_path on the student row
                with sqlite3.connect('students.db', timeout=10) as conn:
                    conn.execute("UPDATE students SET placard_path = ? WHERE id = ?", (placard_path, student_id))

                # 4. Move files from temporary staging to permanent private storage
                if os.path.exists(profile_tmp_path):
                    shutil.move(profile_tmp_path, final_profile_path)
                if os.path.exists(payment_tmp_path):
                    shutil.move(payment_tmp_path, final_payment_path)
            except Exception as e:
                # Cleanup on failure: delete student record and clean up any generated files
                with sqlite3.connect('students.db', timeout=10) as conn:
                    conn.execute("DELETE FROM students WHERE id = ?", (student_id,))
                if os.path.exists(profile_tmp_path):
                    try: os.remove(profile_tmp_path)
                    except: pass
                if os.path.exists(payment_tmp_path):
                    try: os.remove(payment_tmp_path)
                    except: pass
                if placard_path and os.path.exists(placard_path):
                    try: os.remove(placard_path)
                    except: pass
                ticket_path = os.path.join(STORAGE_TICKETS, f"ticket_{roll_number_clean}.png")
                if os.path.exists(ticket_path):
                    try: os.remove(ticket_path)
                    except: pass
                raise e

            # Offload email sending to background thread pool
            EMAIL_EXECUTOR.submit(send_email_async, student_id, form.email.data, placard_path)
            
            # Clear any abuse tracking for this IP on successful registration
            ABUSE_TRACKER.pop(client_ip, None)
            
            # POST-Redirect-GET: redirect to success page using unguessable token
            return redirect(url_for('success_page', public_token=public_token))
        
        except Exception as e:
            return render_template('index.html', form=form, error=str(e))
    
    return render_template('index.html', form=form)

if __name__ == '__main__':
    init_db()
    ensure_test_images()
    flask_debug = os.getenv('FLASK_DEBUG', 'False').lower() in ('true', '1', 't')
    app.run(host='0.0.0.0', port=5000, debug=flask_debug)