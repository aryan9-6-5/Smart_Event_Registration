import os
import shutil
import tempfile
import sqlite3
import pytest
from PIL import Image

import app as flask_app

@pytest.fixture(scope="session")
def test_env(tmp_path_factory):
    temp_dir = tmp_path_factory.mktemp("test_env")
    temp_db = str(temp_dir / "test_students.db")
    
    # Store original connect
    orig_connect = sqlite3.connect
    
    def patched_connect(database, *args, **kwargs):
        if database == 'students.db':
            return orig_connect(temp_db, *args, **kwargs)
        return orig_connect(database, *args, **kwargs)
        
    return {
        "temp_dir": temp_dir,
        "temp_db": temp_db,
        "orig_connect": orig_connect,
        "patched_connect": patched_connect
    }

@pytest.fixture(autouse=True)
def isolate_db_and_smtp(test_env, monkeypatch):
    monkeypatch.setattr(sqlite3, "connect", test_env["patched_connect"])
    
    # Mock SMTP sending so tests never hit external network
    monkeypatch.setattr(flask_app, "send_email", lambda to, placard: True)
    monkeypatch.setattr(flask_app, "send_abuse_warning_email", lambda ip, ua, form: True)
    
    # Initialize DB in the test database
    flask_app.init_db()

    # Reset in-memory abuse state so one test's failures never block the next
    flask_app.ABUSE_TRACKER.clear()
    flask_app.FLAGGED_IPS.clear()

    # Clear tables between tests for isolation
    with test_env["patched_connect"](test_env["temp_db"]) as conn:
        conn.execute("DELETE FROM students")
        conn.execute("DELETE FROM uploads")
        conn.execute("DELETE FROM abuse_attempts")


@pytest.fixture
def app(test_env):
    flask_app.app.config.update({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SECRET_KEY": "test-secret-key",
        "RATELIMIT_ENABLED": False
    })
    flask_app.limiter.enabled = False
    return flask_app.app

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def dummy_image(tmp_path):
    img_path = tmp_path / "sample.png"
    img = Image.new("RGB", (100, 100), color="blue")
    img.save(str(img_path))
    return str(img_path)
