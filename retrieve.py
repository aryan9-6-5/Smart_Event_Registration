import os
import shutil
import zipfile
import json
import sqlite3
from datetime import datetime

# Define directories to archive and clear
# Current secure storage paths
STORAGE_PROFILES = "storage/profiles"
STORAGE_PAYMENTS = "storage/payments"
STORAGE_TMP = "storage/tmp"
STORAGE_PLACARDS = "storage/placards"
STORAGE_TICKETS = "storage/tickets"

# Legacy / public static directories
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
    """Zips all student registration data (profiles, payments, tickets, placards, theme, config, and db)."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = os.path.join(BACKUP_DIR, f"retrieved_data_{timestamp}.zip")
    
    print(f"📦 Starting backup to {zip_path}...")

    # Flush any SQLite WAL entries into the database before zipping
    if os.path.exists(DB_FILE):
        conn = None
        try:
            conn = sqlite3.connect(DB_FILE, timeout=5)
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except Exception as e:
            print(f"   [INFO] WAL checkpoint skipped: {e}")
        finally:
            if conn:
                conn.close()
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # 1. Add database file(s)
        for db_related in [DB_FILE, f"{DB_FILE}-wal", f"{DB_FILE}-shm"]:
            if os.path.exists(db_related):
                zip_file.write(db_related, os.path.basename(db_related))
                print(f"   + Added database file: {db_related}")
            
        # 2. Add current configuration file
        if os.path.exists(CONFIG_FILE):
            zip_file.write(CONFIG_FILE, os.path.basename(CONFIG_FILE))
            print(f"   + Added config: {CONFIG_FILE}")

        # 3. Add theme configuration and custom banner assets
        if os.path.exists("theme"):
            for root, _, files in os.walk("theme"):
                for file in files:
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, "theme")
                    zip_file.write(file_path, os.path.join("theme", rel_path))
            print("   + Added theme configurations and banner assets")
            
        # 4. Add directory contents (both secure storage and static uploads)
        dirs_to_zip = {
            STORAGE_PROFILES: "profiles",
            STORAGE_PAYMENTS: "payments",
            STORAGE_TMP: "tmp_uploads",
            STORAGE_PLACARDS: "placards",
            STORAGE_TICKETS: "tickets",
            UPLOADS_PROFILES: "legacy_static_profiles",
            UPLOADS_PAYMENTS: "legacy_static_payments",
            UPLOADS_TMP: "legacy_static_tmp",
            PLACARDS_DIR: "legacy_static_placards",
            TICKETS_DIR: "legacy_static_tickets"
        }
        
        for dir_path, zip_subfolder in dirs_to_zip.items():
            if os.path.exists(dir_path):
                file_count = 0
                for root, _, files in os.walk(dir_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        # Create a clean path inside the zip file
                        rel_path = os.path.relpath(file_path, dir_path)
                        zip_entry_name = os.path.join(zip_subfolder, rel_path)
                        zip_file.write(file_path, zip_entry_name)
                        file_count += 1
                if file_count > 0:
                    print(f"   + Added {file_count} files from: {dir_path}")
                
    print(f"✅ Backup created successfully at {zip_path}\n")
    return zip_path

def delete_database():
    """Deletes or cleanly resets the SQLite database file."""
    if not os.path.exists(DB_FILE):
        print("ℹ️ Database does not exist, nothing to delete.")
        return

    # Checkpoint WAL first and close connection explicitly
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE, timeout=5)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass
    finally:
        if conn:
            conn.close()

    # Try removing the files directly
    deleted = False
    for db_related in [DB_FILE, f"{DB_FILE}-wal", f"{DB_FILE}-shm"]:
        if os.path.exists(db_related):
            try:
                os.remove(db_related)
                print(f"🗑️ Deleted database file: {db_related}")
                deleted = True
            except PermissionError:
                # File is locked by a running process (e.g. Waitress). Wipe tables via SQL.
                print(f"⚠️ {db_related} is locked by active server process; clearing all rows via SQL...")
                sql_conn = None
                try:
                    sql_conn = sqlite3.connect(DB_FILE, timeout=5)
                    sql_conn.isolation_level = None  # autocommit mode allows VACUUM
                    for tbl in ['students', 'uploads', 'abuse_attempts']:
                        try:
                            sql_conn.execute(f"DELETE FROM {tbl}")
                        except Exception:
                            pass
                    try:
                        sql_conn.execute("VACUUM")
                    except Exception:
                        pass
                    print(f"✅ Cleared all student and upload rows in {DB_FILE} via SQL.")
                    deleted = True
                except Exception as err:
                    print(f"❌ Failed to clear database via SQL: {err}")
                finally:
                    if sql_conn:
                        sql_conn.close()
            except Exception as e:
                print(f"❌ Failed to delete {db_related}: {e}")

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
    clear_directory(STORAGE_PROFILES, preserve=["test_profile.jpg"])
    clear_directory(STORAGE_PAYMENTS, preserve=["test_payment.jpg"])
    clear_directory(STORAGE_TMP)
    clear_directory(STORAGE_PLACARDS)
    clear_directory(STORAGE_TICKETS)
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

