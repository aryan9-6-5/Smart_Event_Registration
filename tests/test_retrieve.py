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
