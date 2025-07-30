import os
import uuid
import qrcode
import sqlite3
import smtplib
import secrets
from email.message import EmailMessage
from flask import Flask, request, render_template, url_for, jsonify
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
os.makedirs("static/placards", exist_ok=True)
os.makedirs("static/tickets", exist_ok=True)

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
    name = StringField('Name', validators=[DataRequired(), Length(min=2, max=100)])
    email = EmailField('Email', validators=[DataRequired(), Email()])
    roll_number = StringField('Roll Number', validators=[DataRequired(), Length(min=2, max=20)])
    dept_name = StringField('Department', validators=[DataRequired(), Length(max=100)])
    college_name = StringField('College', validators=[DataRequired(), Length(max=100)])
    trans_id = StringField('Transaction ID', validators=[DataRequired(), Length(min=5, max=50)])
    phone = StringField('Phone', validators=[DataRequired(), Regexp(r'^\d{10}$')])
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
    with sqlite3.connect('students.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, email TEXT, roll_number TEXT UNIQUE,
            dept_name TEXT, college_name TEXT, trans_id TEXT UNIQUE,
            phone TEXT, profile_path TEXT, payment_path TEXT,
            placard_path TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    placard = Image.new('RGB', (1000, 600), '#ffffff')  # Smaller canvas
    draw = ImageDraw.Draw(placard)

    try:
        title_font = ImageFont.truetype('static/fonts/Poppins-Bold.ttf', 52)
        header_font = ImageFont.truetype('static/fonts/Poppins-SemiBold.ttf', 40)
        text_font = ImageFont.truetype('static/fonts/Poppins-Regular.ttf', 36)
    except IOError:
        print("Font loading error - using default font")
        title_font = header_font = text_font = ImageFont.load_default()

    # Header bar
    draw.rectangle([(0, 0), (1000, 100)], fill='#1a237e')
    draw.text((500, 50), "College Tech Summit 2024", fill='#ffffff', font=title_font, anchor='mm')

    # Load profile image
    try:
        profile = Image.open(profile_path).convert('RGB')
        profile.thumbnail((350, 350), Image.Resampling.LANCZOS)
        placard.paste(profile, (40, 130))
    except Exception as e:
        print(f"⚠️ Error loading profile image: {e}")
        placeholder = Image.new('RGB', (350, 350), color='gray')
        draw_p = ImageDraw.Draw(placeholder)
        draw_p.text((175, 175), "No Image", fill="white", font=header_font, anchor='mm')
        placard.paste(placeholder, (40, 130))

    # User details
    details = [("Name", name), ("Roll Number", roll), ("Department", dept),
               ("College", college), ("Phone", phone)]
    y_offset = 140
    for label, value in details:
        draw.text((420, y_offset), f"{label}:", fill='#1a237e', font=header_font)
        draw.text((620, y_offset), value, fill='#1a237e', font=text_font)
        y_offset += 60

    # QR Code generation
    qr_data = f"TECH24-{roll}"
    qr_img = qrcode.make(qr_data)
    qr_path = f"static/tickets/ticket_{roll}.png"
    qr_img.save(qr_path)

    qr = Image.open(qr_path).resize((180, 180), Image.Resampling.LANCZOS)
    placard.paste(qr, (780, 390))

    # Footer bar
    draw.rectangle([(0, 560), (1000, 600)], fill='#1a237e')
    draw.text((500, 580), "Bring this placard to the event for entry", 
              fill='#ffffff', font=text_font, anchor='mm')

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

@app.route('/upload', methods=['POST'])
def upload_file():
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
    
    # Generate unique filename
    roll_number = request.form.get('roll', '').strip().upper()
    ext = os.path.splitext(file.filename)[1] or ".png"
    
    if dir_type == 'profiles':
        filename = f"{roll_number}_profile{ext}"
    elif dir_type == 'payments':
        filename = f"{roll_number}_payment{ext}"
    else:
        filename = f"{roll_number or uuid.uuid4()}_file{ext}"

    filepath = os.path.join('static', 'uploads', dir_type, filename)
    
    print(f"Target filepath: {filepath}")
    
    try:
        # Ensure upload directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        print(f"Directory verified/created: {os.path.dirname(filepath)}")
        
        # Save the uploaded file
        file.save(filepath)
        print(f"File saved to: {filepath}")
        
        response_data = {
            'message': 'File uploaded successfully',
            'path': filepath
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
        if email_sent:
            return render_template('success.html', placard_url=url_for('static', filename=f'placards/placard_{TEST_DATA["roll_number"]}.jpg'))
        else:
            return "Test email failed, but placard was generated successfully.", 500
    
    except Exception as e:
        return f"Test failed: {str(e)}", 500

@app.route('/', methods=['GET', 'POST'])
def index():
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
            
            send_email(data["email"], placard_path)
            return render_template('success.html', placard_url=url_for('static', filename=f'placards/placard_{data["roll_number"]}.jpg'))
            
        except Exception as e:
            return render_template('index.html', form=form, error=f"Test error: {str(e)}")
    if not form.validate_on_submit():
        print("❌ Form validation failed")
        print("Form errors:", form.errors)
    elif form.validate_on_submit():
        print("Form submitted with data:", {field.name: field.data for field in form})
        print("✅ form.validate_on_submit passed")
        try:
            profile_path = form.profile_path.data
            payment_path = form.payment_path.data
            
            if not profile_path or not os.path.exists(profile_path):
                return render_template('index.html', form=form, error="Profile photo is required")
                
            if not payment_path or not os.path.exists(payment_path):
                return render_template('index.html', form=form, error="Payment proof is required")
            
            # Check if roll number or transaction ID already exists
            with sqlite3.connect('students.db') as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT roll_number FROM students WHERE roll_number = ?", (form.roll_number.data,))
                if cursor.fetchone():
                    return render_template('index.html', form=form, error="Roll number already registered")
                
                cursor.execute("SELECT trans_id FROM students WHERE trans_id = ?", (form.trans_id.data,))
                if cursor.fetchone():
                    return render_template('index.html', form=form, error="Transaction ID already used")
            
            placard_path = generate_placard(
                form.name.data,
                form.roll_number.data,
                form.dept_name.data,
                form.college_name.data,
                form.phone.data,
                profile_path
            )

            with sqlite3.connect('students.db') as conn:
                conn.execute('''
                    INSERT INTO students 
                    (name, email, roll_number, dept_name, college_name, 
                     trans_id, phone, profile_path, payment_path, placard_path)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                ''', (
                    form.name.data, form.email.data, form.roll_number.data,
                    form.dept_name.data, form.college_name.data,
                    form.trans_id.data, form.phone.data,
                    profile_path, payment_path, placard_path
                ))

            email_sent = send_email(form.email.data, placard_path)
            return render_template('success.html', placard_url=url_for('static', filename=f'placards/placard_{form.roll_number.data}.jpg'), email_sent=email_sent)
        
        except Exception as e:
            return render_template('index.html', form=form, error=str(e))
    
    return render_template('index.html', form=form)

if __name__ == '__main__':
    init_db()
    ensure_test_images()
    app.run(host='0.0.0.0', port=5000, debug=True)