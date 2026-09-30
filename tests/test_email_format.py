import sqlite3
from email import message_from_bytes, policy

import pytest
from PIL import Image

import app as flask_app
import email_builder as EB

EVENT = {'title': 'College Tech Summit 2024', 'subtitle': 'OFFICIAL REGISTRATION PASS', 'date': 'OCTOBER 24, 2024'}
COLORS = {'primary': '#1E40AF', 'primary_text': '#FFFFFF', 'text': '#0F1B3D', 'muted': '#4F5F82',
          'bg': '#EFF4FC', 'surface': '#FFFFFF', 'border': '#D3DEF2'}
DETAILS = {'name': 'Aryan Hanumakonda', 'roll_number': '23881A6623', 'dept_name': 'CSM',
           'college_name': 'Vardhaman College', 'ticket_id': 'TECH24-23881A6623', 'review_reason': ''}


@pytest.fixture
def placard(tmp_path):
    path = tmp_path / 'placard.jpg'
    Image.new('RGB', (300, 200), 'navy').save(path)
    return str(path)


def _build(placard, pending=False, **over):
    details = dict(DETAILS, **over)
    return EB.build_registration_email(sender='events@example.com', to_email='a@example.com', event=EVENT,
                                       colors=COLORS, details=details, placard_path=placard, pending=pending)


def _parts(msg):
    text = msg.get_body(preferencelist=('plain',)).get_content()
    html = msg.get_body(preferencelist=('html',)).get_content()
    return text, html


# ── structure ────────────────────────────────────────────────────────────────
def test_email_has_plain_and_html_versions_and_attachment(placard):
    msg = _build(placard)
    text, html = _parts(msg)
    assert text.strip() and '<html' in html.lower()
    attachments = [p for p in msg.iter_attachments()]
    assert [a.get_filename() for a in attachments] == ['ticket-23881A6623.jpg']


def test_placard_is_shown_inline_in_the_html(placard):
    msg = _build(placard)
    _, html = _parts(msg)
    assert 'cid:placard' in html
    assert 'image/jpeg' in msg.as_string()


def test_email_survives_missing_placard_file(tmp_path):
    msg = _build(str(tmp_path / 'gone.jpg'))
    text, html = _parts(msg)
    assert 'cid:placard' not in html
    assert not list(msg.iter_attachments())
    assert 'Aryan' in text


def test_sender_shows_event_name_and_survives_serialisation(placard):
    msg = _build(placard)
    assert 'College Tech Summit 2024' in msg['From'] and 'events@example.com' in msg['From']
    parsed = message_from_bytes(msg.as_bytes(), policy=policy.default)
    assert parsed['To'] == 'a@example.com'


# ── confirmed wording ────────────────────────────────────────────────────────
def test_confirmed_email_is_clear_and_actionable(placard):
    msg = _build(placard)
    text, html = _parts(msg)
    assert msg['Subject'] == 'Your ticket for College Tech Summit 2024'
    for body in (text, html):
        assert 'Aryan Hanumakonda' in body
        assert '23881A6623' in body
        assert 'TECH24-23881A6623' in body
        assert 'OCTOBER 24, 2024'.title() in body or 'October 24, 2024' in body or 'OCTOBER 24, 2024' in body
        assert 'confirmed' in body.lower()
    assert 'QR' in text
    assert 'review' not in text.lower()


# ── pending wording ──────────────────────────────────────────────────────────
def test_pending_email_says_ticket_is_not_valid_yet(placard):
    msg = _build(placard, pending=True, review_reason='underpaid')
    text, html = _parts(msg)
    assert 'under review' in msg['Subject'].lower()
    for body in (text, html):
        assert 'not valid' in body.lower() or 'not yet valid' in body.lower()
        assert 'lower than the registration fee' in body
    assert 'is confirmed' not in text.lower()


@pytest.mark.parametrize('reason,phrase', [
    ('duplicate screenshot', 'same as one'),
    ('transaction ID typed manually', 'transaction ID'),
    ('overpaid', 'higher than the registration fee'),
    ('amount not readable', 'could not read the amount'),
])
def test_pending_reasons_are_explained_in_plain_language(placard, reason, phrase):
    text, _ = _parts(_build(placard, pending=True, review_reason=reason))
    assert phrase in text
    assert reason not in text or reason == 'transaction ID typed manually' or reason == 'overpaid'


def test_pending_without_reasons_still_reads_well(placard):
    text, _ = _parts(_build(placard, pending=True, review_reason=''))
    assert 'organizer' in text.lower()


# ── safety ───────────────────────────────────────────────────────────────────
def test_user_supplied_values_are_html_escaped(placard):
    msg = _build(placard, name='<script>alert(1)</script>', college_name='A & B <b>College</b>')
    _, html = _parts(msg)
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert '<b>College</b>' not in html and 'A &amp; B' in html


def test_header_injection_in_event_title_is_neutralised(placard):
    evil = dict(EVENT, title='Summit\r\nBcc: victim@example.com')
    msg = EB.build_registration_email(sender='e@example.com', to_email='a@example.com', event=evil,
                                      colors=COLORS, details=DETAILS, placard_path=placard, pending=False)
    raw = msg.as_bytes().decode('utf-8', 'replace')
    assert '\nBcc:' not in raw


def test_theme_primary_colour_is_used_in_html(placard):
    _, html = _parts(_build(placard))
    assert COLORS['primary'] in html


# ── wiring into the app ──────────────────────────────────────────────────────
def test_send_email_uses_builder_and_smtp(monkeypatch, placard, real_send_email):
    sent = {}

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def ehlo(self): pass
        def starttls(self): pass
        def login(self, *a): pass
        def send_message(self, msg): sent['msg'] = msg
        def quit(self): pass

    monkeypatch.setattr(flask_app.smtplib, 'SMTP', FakeSMTP)
    ok = real_send_email('a@example.com', placard, pending=False, details=dict(DETAILS))
    assert ok is True
    assert sent['msg'].get_body(preferencelist=('html',)) is not None


def test_send_email_async_loads_student_details_from_db(monkeypatch, placard):
    captured = {}
    monkeypatch.setattr(flask_app, 'send_email',
                        lambda to, path, **kw: captured.update(kw) or True)
    with sqlite3.connect('students.db') as conn:
        conn.execute("INSERT INTO students (name,email,roll_number,dept_name,college_name,trans_id,status,review_reason) "
                     "VALUES ('Dee','d@x.com','EM1','ECE','Coll','TEM1','PENDING','underpaid')")
        sid = conn.execute("SELECT id FROM students WHERE roll_number='EM1'").fetchone()[0]
    assert flask_app.send_email_async(sid, 'd@x.com', placard, True) is True
    details = captured['details']
    assert details['name'] == 'Dee' and details['roll_number'] == 'EM1'
    assert details['ticket_id'].endswith('EM1') and details['review_reason'] == 'underpaid'


def test_email_uses_theme_font(placard):
    msg = EB.build_registration_email(
        sender='events@example.com', to_email='a@example.com', event=EVENT,
        colors=COLORS, details=DETAILS, placard_path=placard,
        font={'family': 'Poppins', 'weights': [400, 600]}
    )
    _, html = _parts(msg)
    assert 'Poppins' in html
    assert 'fonts.googleapis.com' in html


def test_email_includes_banner_when_available(tmp_path, placard):
    banner_file = tmp_path / 'banner.jpg'
    Image.new('RGB', (600, 150), '#000000').save(banner_file)
    msg = EB.build_registration_email(
        sender='events@example.com', to_email='a@example.com', event=EVENT,
        colors=COLORS, details=DETAILS, placard_path=placard,
        banner_path=str(banner_file)
    )
    _, html = _parts(msg)
    assert 'cid:banner' in html
    # Attachments list should still only contain the ticket attachment, not inline parts
    attachments = [p for p in msg.iter_attachments()]
    assert [a.get_filename() for a in attachments] == ['ticket-23881A6623.jpg']


def test_email_missing_banner_file_handled_gracefully(tmp_path, placard):
    msg = EB.build_registration_email(
        sender='events@example.com', to_email='a@example.com', event=EVENT,
        colors=COLORS, details=DETAILS, placard_path=placard,
        banner_path=str(tmp_path / 'non_existent_banner.jpg')
    )
    _, html = _parts(msg)
    assert 'cid:banner' not in html
    attachments = [p for p in msg.iter_attachments()]
    assert [a.get_filename() for a in attachments] == ['ticket-23881A6623.jpg']


def test_email_none_font_handled_gracefully(placard):
    msg = EB.build_registration_email(
        sender='events@example.com', to_email='a@example.com', event=EVENT,
        colors=COLORS, details=DETAILS, placard_path=placard,
        font=None
    )
    _, html = _parts(msg)
    assert '<html' in html.lower()
    assert 'fonts.googleapis.com' in html

