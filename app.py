import os
import uuid
import qrcode
import sqlite3
import smtplib
import secrets
import time
import json
import shutil
from datetime import datetime
from collections import defaultdict
from email.message import EmailMessage
from flask import Flask, request, render_template, url_for, jsonify, redirect
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
from flask_wtf import FlaskForm, CSRFProtect
from wtforms import StringField, EmailField
from wtforms.validators import DataRequired, Email, Length, Regexp
import pytesseract
from PIL import Image
import re
load_dotenv()

app = Flask(__name__, static_folder='static', static_url_path='')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(24))  # Fallback to random key if not set
csrf = CSRFProtect(app)

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

print("USING:", os.getenv("SMTP_EMAIL"), os.getenv("SMTP_PASSWORD"))
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
        
        server = smtplib.SMTP(SMTP_CONFIG['server'], SMTP_CONFIG['port'])
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(SMTP_CONFIG['email'], SMTP_CONFIG['password'])
        server.send_message(msg)
        server.quit()
        print(f"[ALERT] Abuse warning email sent for IP: {ip}")
    except Exception as e:
        print(f"[WARN] Failed to send abuse warning email: {e}")

# Test profile and payment images
TEST_PROFILE_PATH = "static/uploads/profiles/test_profile.jpg"
TEST_PAYMENT_PATH = "static/uploads/payments/test_payment.jpg"

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def extract_transaction_id(image_path):
    try:
        text = pytesseract.image_to_string(Image.open(image_path))
        print("OCR Output:", text)

        patterns = [
            r"txn[^\w]?id[^\w]?:?\s*([A-Z0-9]{6,})",         # txn id: ABC1234
            r"Transaction[^\w]*ID[^\w]?:?\s*([A-Z0-9]{6,})",  # Transaction ID: ABC1234
            r"UPI[^\w]*Ref[^\w]?:?\s*([A-Z0-9]{6,})",         # UPI Ref: XYZ456
            r"([A-Z0-9]{8,})"                                 # Catch fallback 8+ character alphanumeric strings
        ]

        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1)

    except Exception as e:
        print("OCR error:", e)

    return None
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
        Length(min=2, max=20, message="Roll number must be between 2 and 20 characters.")
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
        Length(min=5, max=50, message="Transaction ID must be between 5 and 50 characters.")
    ])
    phone = StringField('Phone', validators=[
        DataRequired(message="Phone number is required."),
        Regexp(r'^\d{10}$', message="Phone number must be exactly 10 digits. No spaces, dashes, or country codes.")
    ])
    profile_path = StringField()
    payment_path = StringField()

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
    tmp_dir = "static/uploads/tmp"
    if os.path.exists(tmp_dir):
        try:
            for f in os.listdir(tmp_dir):
                file_path = os.path.join(tmp_dir, f)
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
            placard_path TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Check and add created_at column if it is missing in the database
        cursor.execute("PRAGMA table_info(students)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'created_at' not in columns:
            try:
                cursor.execute("ALTER TABLE students ADD COLUMN created_at TIMESTAMP DEFAULT '2026-06-24 00:00:00'")
                conn.commit()
                print("Added missing created_at column to students table.")
            except Exception as e:
                print(f"Error adding created_at column: {e}")

        cursor.execute('''CREATE TABLE IF NOT EXISTS abuse_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_address TEXT NOT NULL,
            user_agent TEXT,
            form_data_snippet TEXT,
            created_at TEXT NOT NULL
        )''')

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

def generate_placard(name, roll, dept, college, phone, profile_path):
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

    # QR Code generation
    qr_data = f"{config['ticket_prefix']}{roll}"
    qr_img = qrcode.make(qr_data)
    qr_path = f"static/tickets/ticket_{roll}.png"
    os.makedirs(os.path.dirname(qr_path), exist_ok=True)
    qr_img.save(qr_path)

    qr = Image.open(qr_path).resize((200, 200), Image.Resampling.LANCZOS)
    placard.paste(qr, (750, 180))

    # Ticket ID below QR
    draw.text((850, 420), "TICKET ID", fill=COLOR_SECONDARY, font=font_label, anchor='mm')
    draw.text((850, 445), f"{config['ticket_prefix']}{roll}", fill=COLOR_PRIMARY, font=font_value, anchor='mm')

    # Date info at bottom of the stub
    draw.text((850, 530), config['date'].upper(), fill=COLOR_SECONDARY, font=font_footer, anchor='mm')

    placard_path = f"static/placards/placard_{roll}.jpg"
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
        server = smtplib.SMTP(SMTP_CONFIG['server'], SMTP_CONFIG['port'])
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

def cleanup_old_temp_files(max_age_seconds=1800):  # 30 minutes
    tmp_dir = "static/uploads/tmp"
    if os.path.exists(tmp_dir):
        try:
            now = time.time()
            for f in os.listdir(tmp_dir):
                file_path = os.path.join(tmp_dir, f)
                if os.path.isfile(file_path):
                    if now - os.path.getmtime(file_path) > max_age_seconds:
                        os.remove(file_path)
            print("Cleanup of older temporary upload files completed.")
        except Exception as e:
            print(f"Error cleaning old temp files: {e}")

@app.route('/upload', methods=['POST'])
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
        dir_type = 'profiles'
    elif upload_type in ['payment', 'payments']:
        dir_type = 'payments'
    else:
        dir_type = 'profiles'  # fallback

    print(f"Selected directory: {dir_type}")
    
    # Generate unique filename in the temporary folder
    ext = os.path.splitext(file.filename)[1] or ".png"
    unique_id = uuid.uuid4().hex
    
    if dir_type == 'profiles':
        filename = f"tmp_profile_{unique_id}{ext}"
    elif dir_type == 'payments':
        filename = f"tmp_payment_{unique_id}{ext}"
    else:
        filename = f"tmp_file_{unique_id}{ext}"

    filepath = os.path.join('static', 'uploads', 'tmp', filename)
    
    print(f"Target temp filepath: {filepath}")
    
    try:
        # Ensure upload directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        print(f"Directory verified/created: {os.path.dirname(filepath)}")
        
        # Save the uploaded file
        file.save(filepath)
        print(f"File saved to temp: {filepath}")
        
        response_data = {
            'message': 'File uploaded successfully',
            'path': filepath.replace('\\', '/')  # Ensure forward slashes for URLs/JSON
        }

        # OCR only for payment screenshots
        if dir_type == 'payments':
            trans_id = extract_transaction_id(filepath)
            print(f"OCR extracted Transaction ID: {trans_id}")
            response_data['trans_id'] = trans_id or ""

        return jsonify(response_data), 200

    except Exception as e:
        error_msg = f"Failed to save file: {str(e)}"
        print(error_msg)
        return jsonify({'error': error_msg}), 500


@app.route('/test', methods=['GET'])
def test_registration():
    try:
        placard_path = generate_placard(
            TEST_DATA["name"],
            TEST_DATA["roll_number"],
            TEST_DATA["dept_name"],
            TEST_DATA["college_name"],
            TEST_DATA["phone"],
            TEST_DATA["profile_path"]
        )
        
        email_sent = send_email(TEST_DATA["email"], placard_path)
        return redirect(url_for('success_page', roll_number=TEST_DATA['roll_number'], email_failed=(0 if email_sent else 1)))
    
    except Exception as e:
        return f"Test failed: {str(e)}", 500


@app.route('/success/<roll_number>', methods=['GET'])
def success_page(roll_number):
    """Dedicated GET route for the success page — prevents resubmission on refresh."""
    import os
    placard_filename = f'placards/placard_{roll_number}.jpg'
    placard_full_path = os.path.join('static', placard_filename)
    if not os.path.exists(placard_full_path):
        return redirect(url_for('index'))
    email_failed = request.args.get('email_failed') == '1'
    return render_template('success.html', 
        placard_url=url_for('static', filename=placard_filename),
        email_failed=email_failed)

@app.route('/', methods=['GET', 'POST'])
def index():
    cleanup_old_temp_files()
    form = RegistrationForm()
    
    if request.method == 'POST' and request.form.get('name') == 'test':
        try:
            data = {
                "name": request.form.get('name', TEST_DATA["name"]),
                "email": request.form.get('email', TEST_DATA["email"]),
                "roll_number": request.form.get('roll_number', TEST_DATA["roll_number"]),
                "dept_name": request.form.get('dept_name', TEST_DATA["dept_name"]),
                "college_name": request.form.get('college_name', TEST_DATA["college_name"]),
                "trans_id": request.form.get('trans_id', TEST_DATA["trans_id"]),
                "phone": request.form.get('phone', TEST_DATA["phone"]),
            }
            
            profile_path = request.form.get('profile_path')
            if not profile_path or not os.path.exists(profile_path):
                profile_path = TEST_DATA["profile_path"]
                
            placard_path = generate_placard(
                data["name"],
                data["roll_number"],
                data["dept_name"],
                data["college_name"],
                data["phone"],
                profile_path
            )
            
            email_sent = send_email(data["email"], placard_path)
            return redirect(url_for('success_page', roll_number=data["roll_number"], email_failed=(0 if email_sent else 1)))
            
        except Exception as e:
            return render_template('index.html', form=form, error=f"Test error: {str(e)}")
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
                send_abuse_warning_email(client_ip, user_agent, form_snippet)
                return render_template('index.html', form=form,
                    error="Suspicious activity detected from your connection. We've seen repeated invalid submissions from your credentials. This incident has been reported.",
                    abuse_blocked=True)
            
            # Show a banner to the user that validation failed
            return render_template('index.html', form=form, error="Form validation failed. Please correct the highlighted fields below.")

    elif form.validate_on_submit():
        print("Form submitted with data:", {field.name: field.data for field in form})
        print("[OK] form.validate_on_submit passed")
        try:
            profile_path = form.profile_path.data
            payment_path = form.payment_path.data
            
            # ─── Server-side file existence guard ────────────────────────
            if not profile_path or not profile_path.strip():
                return render_template('index.html', form=form, error="Profile photo is required. Please upload your photo.")
            if not os.path.exists(profile_path):
                return render_template('index.html', form=form, error="Profile photo upload failed or file is missing. Please re-upload.")
                
            if not payment_path or not payment_path.strip():
                return render_template('index.html', form=form, error="Payment proof is required. Please upload your payment screenshot.")
            if not os.path.exists(payment_path):
                return render_template('index.html', form=form, error="Payment proof upload failed or file is missing. Please re-upload.")
            
            # Check if roll number or transaction ID already exists
            roll_number_clean = form.roll_number.data.strip().upper()
            with sqlite3.connect('students.db') as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT roll_number FROM students WHERE roll_number = ?", (roll_number_clean,))
                if cursor.fetchone():
                    return render_template('index.html', form=form, error="This roll number is already registered. Each student can only register once.")
                
                cursor.execute("SELECT trans_id FROM students WHERE trans_id = ?", (form.trans_id.data,))
                if cursor.fetchone():
                    return render_template('index.html', form=form, error="This Transaction ID has already been used. Each payment can only be used for one registration.")

            # Move files from temp to final folders
            profile_ext = os.path.splitext(profile_path)[1] or ".png"
            payment_ext = os.path.splitext(payment_path)[1] or ".png"
            
            final_profile_path = f"static/uploads/profiles/{roll_number_clean}_profile{profile_ext}"
            final_payment_path = f"static/uploads/payments/{roll_number_clean}_payment{payment_ext}"
            
            # Generate placard using the current profile path (which is currently temp or existing)
            placard_path = generate_placard(
                form.name.data,
                roll_number_clean,
                form.dept_name.data,
                form.college_name.data,
                form.phone.data,
                profile_path
            )

            try:
                # 1. Database insert first
                with sqlite3.connect('students.db') as conn:
                    conn.execute('''
                        INSERT INTO students 
                        (name, email, roll_number, dept_name, college_name, 
                         trans_id, phone, profile_path, payment_path, placard_path)
                        VALUES (?,?,?,?,?,?,?,?,?,?)
                    ''', (
                        form.name.data, form.email.data, roll_number_clean,
                        form.dept_name.data, form.college_name.data,
                        form.trans_id.data, form.phone.data,
                        final_profile_path, final_payment_path, placard_path
                    ))
                
                # 2. Database write succeeded, now move/copy files to permanent storage
                if "static/uploads/tmp" in profile_path:
                    shutil.move(profile_path, final_profile_path)
                else:
                    if not os.path.exists(final_profile_path) and os.path.exists(profile_path):
                        shutil.copy(profile_path, final_profile_path)
                        
                if "static/uploads/tmp" in payment_path:
                    shutil.move(payment_path, final_payment_path)
                else:
                    if not os.path.exists(final_payment_path) and os.path.exists(payment_path):
                        shutil.copy(payment_path, final_payment_path)
            except Exception as e:
                # Database write failed: Delete generated files and temp uploads to keep server clean
                if "static/uploads/tmp" in profile_path and os.path.exists(profile_path):
                    try: os.remove(profile_path)
                    except: pass
                if "static/uploads/tmp" in payment_path and os.path.exists(payment_path):
                    try: os.remove(payment_path)
                    except: pass
                if os.path.exists(placard_path):
                    try: os.remove(placard_path)
                    except: pass
                # Also delete the generated ticket QR code
                ticket_path = f"static/tickets/ticket_{roll_number_clean}.png"
                if os.path.exists(ticket_path):
                    try: os.remove(ticket_path)
                    except: pass
                raise e

            email_sent = send_email(form.email.data, placard_path)
            
            # Clear any abuse tracking for this IP on successful registration
            ABUSE_TRACKER.pop(client_ip, None)
            
            # POST-Redirect-GET: redirect to success page to prevent resubmission on refresh
            return redirect(url_for('success_page', roll_number=roll_number_clean, email_failed=(0 if email_sent else 1)))
        
        except Exception as e:
            return render_template('index.html', form=form, error=str(e))
    
    return render_template('index.html', form=form)

if __name__ == '__main__':
    init_db()
    ensure_test_images()
    app.run(host='0.0.0.0', port=5000, debug=True)