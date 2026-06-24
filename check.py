import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# Load configuration from your existing .env file
load_dotenv()

def test_smtp_connection():
    # Retrieve environment variables
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    sender_email = os.getenv("SMTP_EMAIL")
    sender_password = os.getenv("SMTP_PASSWORD")
    
    # We will send a test email to yourself
    receiver_email =os.getenv("sender")  

    if not sender_email or not sender_password:
        print("❌ Error: SMTP_EMAIL or SMTP_PASSWORD not found in your .env file.")
        return

    print(f"🔄 Attempting to connect to {smtp_server}:{smtp_port}...")

    # Create the email message
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg['Subject'] = "Smart Event Registration - SMTP Test Connection"
    
    body = "Success! Your SMTP configuration and app password are working perfectly."
    msg.attach(MIMEText(body, 'plain'))

    try:
        # Establish a secure connection with TLS
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls() 
        
        print("🔄 Authenticating credentials...")
        server.login(sender_email, sender_password)
        
        print("🔄 Sending test email...")
        server.sendmail(sender_email, receiver_email, msg.as_string())
        
        print(f"✨ Success! A test email has been sent to {receiver_email}.")
        
    except smtplib.SMTPAuthenticationError:
        print("❌ Authentication Failed: Please double-check your SMTP_EMAIL and SMTP_PASSWORD (App Password).")
    except smtplib.SMTPConnectError:
        print("❌ Connection Failed: Could not connect to the SMTP server. Check your port or network.")
    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}")
    finally:
        try:
            server.quit()
        except NameError:
            pass # Server was never initialized

if __name__ == "__main__":
    test_smtp_connection()