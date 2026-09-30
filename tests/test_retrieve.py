import os
import zipfile
import json
import sqlite3
import pytest
import retrieve

def test_retrieve_backup_creates_valid_zip(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    db_file = tmp_path / "students.db"
    config_file = tmp_path / "event_config.json"
    storage_profiles = tmp_path / "storage" / "profiles"
    storage_payments = tmp_path / "storage" / "payments"
    
    os.makedirs(storage_profiles, exist_ok=True)
    os.makedirs(storage_payments, exist_ok=True)
    
    (storage_profiles / "dummy_profile.jpg").write_text("profile-data")
    (storage_payments / "dummy_payment.jpg").write_text("payment-data")
    config_file.write_text(json.dumps({"title": "Test Event"}))
    
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("CREATE TABLE students (id INT, name TEXT)")
        conn.execute("INSERT INTO students VALUES (1, 'Alice')")
    
    monkeypatch.setattr(retrieve, "BACKUP_DIR", str(backup_dir))
    monkeypatch.setattr(retrieve, "DB_FILE", str(db_file))
    monkeypatch.setattr(retrieve, "CONFIG_FILE", str(config_file))
    monkeypatch.setattr(retrieve, "STORAGE_PROFILES", str(storage_profiles))
    monkeypatch.setattr(retrieve, "STORAGE_PAYMENTS", str(storage_payments))
    monkeypatch.setattr(retrieve, "STORAGE_TMP", str(tmp_path / "storage" / "tmp"))
    monkeypatch.setattr(retrieve, "STORAGE_PLACARDS", str(tmp_path / "storage" / "placards"))
    monkeypatch.setattr(retrieve, "STORAGE_TICKETS", str(tmp_path / "storage" / "tickets"))
    monkeypatch.setattr(retrieve, "UPLOADS_PROFILES", str(tmp_path / "static" / "profiles"))
    monkeypatch.setattr(retrieve, "UPLOADS_PAYMENTS", str(tmp_path / "static" / "payments"))
    monkeypatch.setattr(retrieve, "UPLOADS_TMP", str(tmp_path / "static" / "tmp"))
    monkeypatch.setattr(retrieve, "PLACARDS_DIR", str(tmp_path / "static" / "placards"))
    monkeypatch.setattr(retrieve, "TICKETS_DIR", str(tmp_path / "static" / "tickets"))
    
    zip_path = retrieve.create_backup()
    assert os.path.exists(zip_path)
    
    with zipfile.ZipFile(zip_path, 'r') as zf:
        names = zf.namelist()
        assert "students.db" in names
        assert "event_config.json" in names
        assert any(n.startswith("profiles/") for n in names)
        assert any(n.startswith("payments/") for n in names)


def test_retrieve_delete_database_unlocked(tmp_path, monkeypatch):
    db_file = tmp_path / "students.db"
    db_file.write_text("dummy-data")
    monkeypatch.setattr(retrieve, "DB_FILE", str(db_file))
    retrieve.delete_database()
    assert not os.path.exists(str(db_file))


def test_retrieve_delete_database_locked_falls_back_to_sql(tmp_path, monkeypatch):
    db_file = tmp_path / "students.db"
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("CREATE TABLE students (id INT, name TEXT)")
        conn.execute("INSERT INTO students VALUES (1, 'Alice')")
        conn.execute("CREATE TABLE uploads (token TEXT)")
        conn.execute("INSERT INTO uploads VALUES ('tok1')")
        conn.execute("CREATE TABLE abuse_attempts (id INT)")
        conn.execute("INSERT INTO abuse_attempts VALUES (1)")
    
    monkeypatch.setattr(retrieve, "DB_FILE", str(db_file))
    
    # Simulate Windows file lock PermissionError on os.remove
    def mock_remove(path):
        raise PermissionError("File locked by process")
    
    monkeypatch.setattr(os, "remove", mock_remove)
    retrieve.delete_database()
    
    # File still exists, but all tables were wiped via SQL
    with sqlite3.connect(str(db_file)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM uploads").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM abuse_attempts").fetchone()[0] == 0


def test_retrieve_clear_directory_preserves_files(tmp_path):
    target_dir = tmp_path / "target"
    os.makedirs(target_dir, exist_ok=True)
    
    (target_dir / "user_photo.jpg").write_text("delete-me")
    (target_dir / "test_profile.jpg").write_text("preserve-me")
    sub_dir = target_dir / "subdir"
    os.makedirs(sub_dir, exist_ok=True)
    (sub_dir / "temp.txt").write_text("delete-me-too")
    
    retrieve.clear_directory(str(target_dir), preserve=["test_profile.jpg"])
    
    assert os.path.exists(str(target_dir / "test_profile.jpg"))
    assert not os.path.exists(str(target_dir / "user_photo.jpg"))
    assert not os.path.exists(str(sub_dir))


def test_retrieve_reset_event_config(tmp_path, monkeypatch):
    config_file = tmp_path / "event_config.json"
    config_file.write_text(json.dumps({"title": "Custom Event", "fee": "1000"}))
    monkeypatch.setattr(retrieve, "CONFIG_FILE", str(config_file))
    
    retrieve.reset_event_config()
    
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["title"] == retrieve.TEMPLATE_EVENT_CONFIG["title"]
    assert data["fee"] == retrieve.TEMPLATE_EVENT_CONFIG["fee"]

