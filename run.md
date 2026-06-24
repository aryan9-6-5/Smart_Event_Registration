# How to Run the Smart Event Registration System

Follow these steps to set up and run the application on your local machine.

## Prerequisites

1. **Python 3.8+**: Ensure Python is installed. You can check your version by running:
   ```bash
   python --version
   ```
2. **Tesseract-OCR**: The application uses Tesseract for OCR text extraction from payment screenshots.
   - **Windows**: Download and run the installer from [UB-Mannheim's Tesseract page](https://github.com/UB-Mannheim/tesseract/wiki). By default, install it to `C:\Program Files\Tesseract-OCR\tesseract.exe`.
   - **macOS** (Homebrew): `brew install tesseract`
   - **Linux** (APT): `sudo apt-get install tesseract-ocr`

---

## Step-by-Step Setup

### 1. Set Up Virtual Environment

Open a terminal in the project directory (`EventRegistration authenticator`) and run:

```bash
# Create the virtual environment
python -m venv venv

# Activate the virtual environment
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# Windows (Command Prompt):
.\venv\Scripts\activate.bat
# macOS / Linux:
source venv/bin/activate
```

### 2. Install Dependencies

Install the required Python packages:

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a file named `.env` in the root of the project (if it doesn't already exist) and populate it with your configuration:

```env
SECRET_KEY=your_secret_session_key
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_EMAIL=your_email@gmail.com
SMTP_PASSWORD=your_gmail_app_password
```

> [!IMPORTANT]
> If using Gmail, you must generate a **Google App Password** rather than using your main account password. You can do this in your Google Account settings under Security > 2-Step Verification > App Passwords.

### 4. Initialize or Reset the Database

To clean the uploads folders and reset/initialize the SQLite database, run the reset script:

```bash
python reset_db.py
```

This will clear all registered students and initialize a clean database `students.db` with sample test profile and payment photos.

### 5. Start the Application

Run the Flask server:

```bash
python app.py
```

The application will start on `http://127.0.0.1:5000/`.

---

## Verification & Testing

- **Registration Portal**: Open your browser to `http://127.0.0.1:5000/` to test registrations.
- **Fast Test Registration**: Access the automated test route at `http://127.0.0.1:5000/test` to run a mock registration, generate a placard, and attempt to send a verification email to your SMTP email.
