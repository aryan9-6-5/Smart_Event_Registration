import os
import shutil
import zipfile
import json
from datetime import datetime

# Define directories to archive and clear
UPLOADS_PROFILES = "static/uploads/profiles"
UPLOADS_PAYMENTS = "static/uploads/payments"
UPLOADS_TMP = "static/uploads/tmp"
PLACARDS_DIR = "static/placards"
TICKETS_DIR = "static/tickets"
DB_FILE = "students.db"
CONFIG_FILE = "event_config.json"
BACKUP_DIR = "backups"

# Default template event configurations
TEMPLATE_EVENT_CONFIG = {
    "title": "Your Event Title Here",
    "subtitle": "OFFICIAL REGISTRATION PASS",
    "description": "Short description of your event goes here.",
    "fee": "₹500",
    "date": "JANUARY 1, 2027",
    "ticket_prefix": "EVENT-",
    "payment_qr": "images/payment_qr.png"
}

def create_backup():
    """Zips all student registration data (profiles, payments, tickets, placards, config, and db)."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = os.path.join(BACKUP_DIR, f"retrieved_data_{timestamp}.zip")
    
    print(f"📦 Starting backup to {zip_path}...")
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # 1. Add database file
        if os.path.exists(DB_FILE):
            zip_file.write(DB_FILE, os.path.basename(DB_FILE))
            print(f"   + Added database: {DB_FILE}")
            
        # 2. Add current configuration file
        if os.path.exists(CONFIG_FILE):
            zip_file.write(CONFIG_FILE, os.path.basename(CONFIG_FILE))
            print(f"   + Added config: {CONFIG_FILE}")
            
        # 3. Add directory contents
        dirs_to_zip = {
            UPLOADS_PROFILES: "profiles",
            UPLOADS_PAYMENTS: "payments",
            UPLOADS_TMP: "tmp_uploads",
            PLACARDS_DIR: "placards",
            TICKETS_DIR: "tickets"
        }
        
        for dir_path, zip_subfolder in dirs_to_zip.items():
            if os.path.exists(dir_path):
                for root, _, files in os.walk(dir_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        # Create a clean path inside the zip file
                        rel_path = os.path.relpath(file_path, dir_path)
                        zip_entry_name = os.path.join(zip_subfolder, rel_path)
                        zip_file.write(file_path, zip_entry_name)
                print(f"   + Added files from: {dir_path}")
                
    print(f"✅ Backup created successfully at {zip_path}\n")
    return zip_path

def delete_database():
    """Deletes the SQLite database file."""
    if os.path.exists(DB_FILE):
        try:
            # We make sure connection is closed by removing the file directly
            os.remove(DB_FILE)
            print(f"🗑️ Deleted database: {DB_FILE}")
        except Exception as e:
            print(f"❌ Failed to delete database: {e}")
    else:
        print("ℹ️ Database does not exist, nothing to delete.")

def clear_directory(directory_path, preserve=[]):
    """Deletes all files in the directory except for preserved files."""
    if not os.path.exists(directory_path):
        return
        
    for item in os.listdir(directory_path):
        item_path = os.path.join(directory_path, item)
        if os.path.isfile(item_path):
            if any(item.endswith(p) for p in preserve):
                continue
            try:
                os.remove(item_path)
            except Exception as e:
                print(f"❌ Failed to delete {item_path}: {e}")
        elif os.path.isdir(item_path):
            try:
                shutil.rmtree(item_path)
            except Exception as e:
                print(f"❌ Failed to delete directory {item_path}: {e}")

def reset_event_config():
    """Resets the event configuration file to a clean template state."""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(TEMPLATE_EVENT_CONFIG, f, indent=4)
        print(f"🔄 Reset event configurations in {CONFIG_FILE} to template placeholders.")
    except Exception as e:
        print(f"❌ Failed to reset event config: {e}")

def main():
    print("====================================================")
    print("   SMART EVENT REGISTRATION - RETRIEVE & RESET TOOL ")
    print("====================================================\n")
    
    # 1. Back up all records and files
    create_backup()
    
    # 2. Wipe database
    delete_database()
    
    # 3. Clean files (preserving default test files so test suite doesn't break)
    print("🧹 Cleaning file system...")
    clear_directory(UPLOADS_PROFILES, preserve=["test_profile.jpg"])
    clear_directory(UPLOADS_PAYMENTS, preserve=["test_payment.jpg"])
    clear_directory(UPLOADS_TMP)
    clear_directory(PLACARDS_DIR)
    clear_directory(TICKETS_DIR)
    print("✅ Files cleaned (preserved test photos).")
    
    # 4. Reset event configuration template
    reset_event_config()
    
    print("\n🎉 Retrieval and reset complete. The system has been restored to a clean template!")
    print("====================================================")

if __name__ == "__main__":
    main()
