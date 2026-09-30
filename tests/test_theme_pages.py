import copy
import glob
import os
import re
import sqlite3

import pytest
from PIL import Image

import app as flask_app
import theme as T

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEX = re.compile(r'#[0-9A-Fa-f]{3,8}\b')
THEME_COLOR_VARS = ['--bg:', '--surface:', '--text:', '--muted:', '--border:', '--primary:', '--primary-text:']
STATUS_VARS = ['--ok:', '--pending:', '--bad:']


def _custom_theme(**color_overrides):
    data = copy.deepcopy(T.DEFAULT_THEME)
    data['colors'].update(color_overrides)
    T.validate_theme(data)
    return data


def _login(client):
    with client.session_transaction() as s:
        s['admin_logged_in'] = True


def _all_pages(client):
    pages = {'/': client.get('/'), '/admin/login': client.get('/admin/login')}
    _login(client)
    pages['/admin'] = client.get('/admin')
    pages['/admin/checkin'] = client.get('/admin/checkin')
    return pages


# ── theme variables reach every page ─────────────────────────────────────────
def test_every_page_defines_theme_and_status_variables(client):
    for path, resp in _all_pages(client).items():
        assert resp.status_code == 200, path
        html = resp.get_data(as_text=True)
        for var in THEME_COLOR_VARS + STATUS_VARS:
            assert var in html, f'{var} missing on {path}'


def test_success_page_defines_theme_variables(client, tmp_path):
    placard = tmp_path / 'p.jpg'
    Image.new('RGB', (10, 10)).save(placard)
    with sqlite3.connect('students.db') as conn:
        conn.execute("INSERT INTO students (name,email,roll_number,trans_id,status,placard_path,public_token) "
                     "VALUES ('T','t@x.com','TH2','TT2','CONFIRMED',?,'tok2')", (str(placard),))
    html = client.get('/success/tok2').get_data(as_text=True)
    for var in THEME_COLOR_VARS + STATUS_VARS:
        assert var in html


def test_custom_theme_colors_are_injected(client, monkeypatch):
    monkeypatch.setattr(flask_app, 'THEME', _custom_theme(primary='#0E7C6B'))
    assert '--primary: #0E7C6B' in client.get('/').get_data(as_text=True)


def test_status_colors_are_fixed_regardless_of_theme(client, monkeypatch):
    def status_lines(html):
        return [re.search(re.escape(v) + r'\s*[^;]+;', html).group(0) for v in STATUS_VARS]

    plain = status_lines(client.get('/').get_data(as_text=True))
    monkeypatch.setattr(flask_app, 'THEME', _custom_theme(primary='#7C3AED'))
    assert status_lines(client.get('/').get_data(as_text=True)) == plain


def test_font_family_and_weights_in_stylesheet_link(client, monkeypatch):
    data = copy.deepcopy(T.DEFAULT_THEME)
    data['font'] = {'family': 'Work Sans', 'weights': [400, 700]}
    monkeypatch.setattr(flask_app, 'THEME', data)
    html = client.get('/').get_data(as_text=True)
    assert 'family=Work+Sans:wght@400;700' in html
    assert "--font: 'Work Sans'" in html


# ── no hardcoded brand colours outside the fixed status tokens ───────────────
def _strip_comments(text):
    return re.sub(r'/\*.*?\*/', '', text, flags=re.S)


_LINT_FILES = sorted(
    glob.glob(os.path.join(ROOT, 'static', 'css', '*.css')) +
    glob.glob(os.path.join(ROOT, 'static', 'js', '*.js')) +
    [p for p in glob.glob(os.path.join(ROOT, 'templates', '*.html')) if not p.endswith('_theme_head.html')])


@pytest.mark.parametrize('path', _LINT_FILES, ids=[os.path.basename(p) for p in _LINT_FILES])
def test_no_hardcoded_hex_colors(path):
    with open(path, encoding='utf-8') as f:
        found = HEX.findall(_strip_comments(f.read()))
    assert not found, f'{os.path.basename(path)} hardcodes {sorted(set(found))}; use theme variables'


# ── banner band ──────────────────────────────────────────────────────────────
def test_no_banner_means_no_band(client, monkeypatch):
    monkeypatch.setattr(flask_app, 'BANNER_STATIC_PATH', None)
    assert 'class="banner-band"' not in client.get('/').get_data(as_text=True)


def test_banner_band_rendered_with_focus(client, monkeypatch):
    data = copy.deepcopy(T.DEFAULT_THEME)
    data['banner_focus'] = 'top'
    monkeypatch.setattr(flask_app, 'THEME', data)
    monkeypatch.setattr(flask_app, 'BANNER_STATIC_PATH', 'theme/banner.jpg')
    html = client.get('/').get_data(as_text=True)
    assert 'class="banner-band"' in html
    assert '/static/theme/banner.jpg' in html
    assert 'object-position: top' in html


def test_organizer_source_files_are_not_web_reachable(client):
    assert client.get('/theme/banner.jpg').status_code == 404
    assert client.get('/theme/theme.json').status_code == 404


# ── placard follows the theme ────────────────────────────────────────────────
def test_placard_uses_theme_colors(monkeypatch, tmp_path, dummy_image):
    monkeypatch.setattr(flask_app, 'THEME', _custom_theme(bg='#FFEEDD', primary='#0E7C6B'))
    monkeypatch.setattr(flask_app, 'STORAGE_PLACARDS', str(tmp_path))
    monkeypatch.setattr(flask_app, 'STORAGE_TICKETS', str(tmp_path))
    path = flask_app.generate_placard('N', 'PL1', 'CSE', 'C', '9876543210', dummy_image, ticket_secret='s')
    with Image.open(path) as img:
        r, g, b = img.getpixel((400, 570))  # empty area of the left panel
        assert abs(r - 0xFF) < 6 and abs(g - 0xEE) < 6 and abs(b - 0xDD) < 6
        r, g, b = img.getpixel((500, 4))  # primary accent strip
        assert abs(r - 0x0E) < 8 and abs(g - 0x7C) < 8 and abs(b - 0x6B) < 8
