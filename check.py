import os
from dotenv import load_dotenv
load_dotenv()
SMTP_CONFIG = {
    'server': os.getenv('SMTP_SERVER'),
    'port': int(os.getenv('SMTP_PORT')),
    'email': os.getenv('SMTP_EMAIL'),
    'password': os.getenv('SMTP_PASSWORD')
}
print("EMAIL:", os.getenv('SMTP_EMAIL'))
print("PASS :", os.getenv('SMTP_PASSWORD'))