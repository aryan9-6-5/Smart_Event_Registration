import sqlite3
import os
import glob
import shutil

# === 1. Wipe Students Table ===
conn = sqlite3.connect('students.db')
cursor = conn.cursor()
cursor.execute("DELETE FROM students")
cursor.execute("DELETE FROM sqlite_sequence WHERE name='students'")
conn.commit()
conn.close()
print("✅ Database wiped clean.")

# === 2. Clear Uploads (Except Test Files) ===
def clear_folder(folder_path, preserve=[]):
    for file_path in glob.glob(os.path.join(folder_path, "*")):
        if any(os.path.basename(file_path).endswith(p) for p in preserve):
            continue
        try:
            os.remove(file_path)
        except Exception as e:
            print(f"❌ Failed to delete {file_path}: {e}")

uploads_profiles = "static/uploads/profiles"
uploads_payments = "static/uploads/payments"
uploads_tickest= "static/tickets"
uploads_placards= "static/placards"
clear_folder(uploads_profiles, preserve=["test_profile.jpg"])
clear_folder(uploads_payments, preserve=["test_payment.jpg"])
clear_folder(uploads_tickest)
clear_folder(uploads_placards)

print("🧹 Upload folders cleaned (except test files).")
