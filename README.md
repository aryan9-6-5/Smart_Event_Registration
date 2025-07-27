# Smart Event Registration System

#### A Flask web application that handles event registration with file uploads, OCR-based payment verification, and automated placard generation. This project is a complete event registration system built using Flask for the backend and HTML, CSS, and JavaScript for the frontend. It was developed for managing registrations for the College Tech Summit 2024. The system allows students to register for the event by submitting a form that includes their personal details, a profile photo, and a payment screenshot. The backend uses OCR to extract the transaction ID from the uploaded payment proof and pre-fills it in the form to prevent fraudulent reuse. A personalized placard with a QR code is generated for each student and sent via email as confirmation, with a QR code is generated for each student and sent via email as confirmation.
---
## Features

- Student registration form with support for image uploads
- OCR-based transaction ID extraction from payment screenshot
- Duplicate detection for roll number and transaction ID
- Auto-generation of placard with embedded QR code
- Confirmation email with placard attached
- SQLite database to store all registration records
- Clean file naming and folder structure for all uploads
## File Storage Structure
- static/uploads/profiles/<ROLLNUMBER>profile.png
- static/uploads/payments/<ROLLNUMBER>payment.png
- static/placards/placard<ROLLNUMBER>.jpg
- static/tickets/ticket<ROLLNUMBER>.png
## Tech Stack
- Backend: Flask, WTForms, SQLite
- Image Processing: Pillow, qrcode
- OCR: pytesseract + Tesseract
- Frontend: HTML, CSS, JavaScript
- Email: SMTP integration
---
# To run this applications
1. Clone and setup
```bash
git clone https://github.com/yourusername/Smart_Event_Registration.git
cd Smart_Event_Registration
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```
2. Configure environment: Create .env file
```.env
SECRET_KEY=your-secret-key
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_EMAIL=your-email@gmail.com
SMTP_PASSWORD=your-app-password
```
3. Run
```bash
python app.py
```
---
# How does it work?
Students fill registration form and upload profile photo + payment proof
OCR extracts transaction ID from payment screenshot
System generates personalized placard with QR code
Confirmation email sent with placard attachment
All data stored in SQLite database
---
## Future Improvements

- Admin login with analytics dashboard
- PDF generation of tickets and placards
- QR scan check-in functionality for event staff
- Deployment on platforms like Render or Replit
- Migration to PostgreSQL for scalability
