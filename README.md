# Smart Event Registration System

A modern Flask web application that handles event registration with file uploads, OCR-based payment verification, automated placard generation, and dynamic customization. 

This project is a complete event registration system built using Flask for the backend and CSS/JS for the frontend. The system allows students to register for an event by submitting a form that includes their personal details, a profile photo, and a payment screenshot. 

---

## Key Features & Refinements

- **Dynamic Event Configuration**: Manage event metadata (title, fee, date, ticket prefix, payment QR image) dynamically via `event_config.json` without modifying source code.
- **Secure Transaction ID Field**: Once the backend automated OCR extracts the transaction ID from the payment screenshot, the input field is locked as `read-only` to prevent user tampering. If OCR fails, the field remains editable for manual entry.
- **Transactional File Storage & Cleanup**: File uploads are stored in a temporary directory (`static/uploads/tmp/`) and only moved to permanent directories (`profiles/` and `payments/`) after successful database commits.
- **Orphaned Uploads prevention**: If a registration is aborted or database insertion fails, all temporary uploads, generated placards, and ticket assets are instantly purged. Old unsubmitted uploads in `tmp/` are cleaned up automatically.
- **Responsive Payment QR Modal**: The payment instructions card features a premium "Scan & Pay" layout with a visual scanner animation line and a responsive pop-up modal overlay showing the enlarged QR code.
- **Retrieve & Reset Script (`retrieve.py`)**: A utility script that packs all uploaded student profiles, payment screenshots, generated placards, tickets, and the active SQLite database into a timestamped backup ZIP archive. It then deletes the database and clears the uploads folder to reset the project as a template.

---

## File Storage Structure
- `static/uploads/tmp/` — Temporary directory for active session file uploads
- `static/uploads/profiles/<ROLLNUMBER>_profile.png` — Confirmed student profile photos
- `static/uploads/payments/<ROLLNUMBER>_payment.png` — Confirmed payment screenshots
- `static/placards/placard_<ROLLNUMBER>.jpg` — Generated event badges/placards
- `static/tickets/ticket_<ROLLNUMBER>.png` — Generated ticket QR codes

---

## Tech Stack
- **Backend**: Flask, WTForms, SQLite3
- **Image Processing**: Pillow, qrcode
- **OCR**: pytesseract + Tesseract OCR
- **Frontend**: HTML5, Vanilla CSS, JavaScript
- **Email Delivery**: SMTP integration with attachments

---

## How to Run This Application

1. **Clone and Setup**:
   ```bash
   git clone https://github.com/aryan9-6-5/Smart_Event_Registration.git
   cd Smart_Event_Registration
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure Environment variables** by creating a `.env` file in the root directory:
   ```env
   SECRET_KEY=your-secret-key
   SMTP_SERVER=smtp.gmail.com
   SMTP_PORT=587
   SMTP_EMAIL=your-email@gmail.com
   SMTP_PASSWORD=your-app-password
   ```

3. **Configure Event Details**:
   Edit `event_config.json` to customize the event name, date, ticket prefixes, fees, and payment QR image.

4. **Wipe/Reset Database (Developer Tool)**:
   Run the utility script to generate a backup of all data, reset configurations, and wipe the database:
   ```bash
   python retrieve.py
   ```

5. **Start Flask Server**:
   ```bash
   python app.py
   ```

