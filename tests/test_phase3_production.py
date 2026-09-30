import os
import shutil
import pytest
import pytesseract
import app as flask_app

def test_tesseract_cmd_configurable_via_env(monkeypatch):
    """Test: TESSERACT_CMD can be set via environment variable."""
    fake_path = r"C:\fake\path\to\tesseract.exe"
    monkeypatch.setenv("TESSERACT_CMD", fake_path)
    monkeypatch.setattr(os.path, "exists", lambda p: p == fake_path)

    cmd = flask_app.configure_tesseract()
    assert cmd == fake_path
    assert pytesseract.pytesseract.tesseract_cmd == fake_path

def test_tesseract_cmd_fallback_to_shutil_which(monkeypatch):
    """Test: When TESSERACT_CMD is not set, discovery falls back to PATH via shutil.which."""
    monkeypatch.delenv("TESSERACT_CMD", raising=False)
    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/tesseract" if cmd == "tesseract" else None)

    cmd = flask_app.configure_tesseract()
    assert cmd == "/usr/bin/tesseract"
    assert pytesseract.pytesseract.tesseract_cmd == "/usr/bin/tesseract"

def test_security_headers_present(client):
    """Test: Response includes critical HTTP security headers and Content-Security-Policy."""
    resp = client.get('/')
    assert resp.status_code == 200
    assert resp.headers.get('X-Content-Type-Options') == 'nosniff'
    assert resp.headers.get('X-Frame-Options') == 'SAMEORIGIN'
    assert resp.headers.get('Referrer-Policy') == 'strict-origin-when-cross-origin'
    csp = resp.headers.get('Content-Security-Policy')
    assert csp is not None
    assert "default-src 'self'" in csp

def test_proxy_fix_middleware_configuration(monkeypatch):
    """Test: configure_proxy_fix applies ProxyFix when NUM_PROXIES is configured."""
    from werkzeug.middleware.proxy_fix import ProxyFix

    test_app = flask_app.app
    orig_wsgi = test_app.wsgi_app

    try:
        monkeypatch.setenv("NUM_PROXIES", "1")
        flask_app.configure_proxy_fix(test_app)
        assert isinstance(test_app.wsgi_app, ProxyFix)
    finally:
        test_app.wsgi_app = orig_wsgi


