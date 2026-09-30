"""Builds the attendee email: HTML + plain-text versions, ticket shown inline and attached.

Pure functions (no Flask, no SMTP) so the wording and layout are easy to test.
Email clients ignore stylesheets and CSS variables, so colours are inlined as hex values
taken from the event theme; status colours are fixed, like everywhere else in the app.
"""
import html
import os
import re
from email.message import EmailMessage
from email.utils import formataddr

OK_COLOR = '#1F7A45'
OK_BG = '#E3F3EA'
PENDING_COLOR = '#7A4E0A'
PENDING_BG = '#FDF3DC'
FRAUD_COLOR = '#9B1C1C'
FRAUD_BG = '#FDE8E8'

REASON_TEXT = {
    'duplicate screenshot': 'This payment screenshot looks the same as one that was already submitted.',
    'duplicate transaction ID': 'This transaction ID has already been used for another registration.',
    'transaction ID typed manually': 'We could not read the transaction ID from your screenshot automatically, '
                                     'so an organizer needs to check the transaction ID you typed.',
    'underpaid': 'The amount on your screenshot is lower than the registration fee.',
    'overpaid': 'The amount on your screenshot is higher than the registration fee.',
    'amount not readable': 'We could not read the amount on your screenshot.',
    'flagged by admin': 'Your registration was flagged for fraud review by event administrators.',
}


def _one_line(value):
    """Collapse anything that could break out of a header or a single-line field."""
    return re.sub(r'[\r\n]+', ' ', str(value or '')).strip()


def _reasons(review_reason):
    parts = [p.strip() for p in (review_reason or '').split(',') if p.strip()]
    return [REASON_TEXT[p] for p in parts if p in REASON_TEXT]


def _plain(event, details, pending, reasons, fraud=False):
    name = _one_line(details.get('name')) or 'there'
    lines = [f"Hi {name},", ""]
    if fraud:
        lines += [
            f"Your profile is flagged for fraud and is in review by the {event['title']} organizers.",
            "",
            "Your ticket is deactivated and is NOT valid for event entry until an administrator verifies and clears this flag.",
        ]
        if reasons:
            lines += ["", "Why your profile was flagged:"] + [f"- {r}" for r in reasons]
        lines += [
            "",
            "If you believe this is an error, please contact the organizers with your original proof of payment.",
        ]
    elif pending:
        lines += [
            f"Thanks for registering for {event['title']}. We received your registration, and an organizer "
            "is reviewing your payment.",
            "",
            "Your ticket is attached, but it is not valid for entry until your registration is approved. "
            "We will email you again as soon as that happens.",
        ]
        if reasons:
            lines += ["", "Why it needs a check:"] + [f"- {r}" for r in reasons]
        else:
            lines += ["", "An organizer will check your payment proof shortly."]
    else:
        lines += [
            f"You are registered for {event['title']}. Your registration is confirmed.",
            "",
            "Your ticket is attached to this email.",
        ]
    lines += [
        "",
        "Your registration",
        f"  Name:        {_one_line(details.get('name'))}",
        f"  Roll number: {_one_line(details.get('roll_number'))}",
        f"  Ticket ID:   {_one_line(details.get('ticket_id'))}",
        f"  Department:  {_one_line(details.get('dept_name'))}",
        f"  College:     {_one_line(details.get('college_name'))}",
        f"  Date:        {_one_line(event.get('date'))}",
    ]
    if not pending and not fraud:
        lines += ["", "At the event", "Show the QR code on your ticket at the entrance, either printed or on your phone. "
                      "Each ticket can be scanned once."]
    lines += ["", f"- {event['title']} organizers"]
    return "\n".join(lines)


def _row(label, value, colors, font_stack):
    val_esc = html.escape(_one_line(value))
    if label == 'Ticket ID' and val_esc:
        val_display = (f'<span style="display:inline-block;background:{colors["primary"]};color:{colors["primary_text"]};'
                       f'font-size:12px;font-weight:700;padding:2px 8px;border-radius:4px;letter-spacing:0.5px;font-family:{font_stack};">{val_esc}</span>')
    else:
        val_display = val_esc
    return (f'<tr><td style="padding:8px 0;color:{colors["muted"]};font-size:14px;width:130px;font-family:{font_stack};">{html.escape(label)}</td>'
            f'<td style="padding:8px 0;color:{colors["text"]};font-size:14px;font-weight:600;font-family:{font_stack};">{val_display}</td></tr>')


def _html(event, details, colors, pending, reasons, has_image, fraud=False, font=None, has_banner=False):
    esc = lambda v: html.escape(_one_line(v))

    font_family = (font.get('family') if isinstance(font, dict) else None) or 'Poppins'
    weights = (font.get('weights') if isinstance(font, dict) else None) or [400, 600]
    weights_str = ';'.join(str(w) for w in sorted(weights)) if weights else '400;600'
    family_param = font_family.replace(' ', '+')
    font_url = f"https://fonts.googleapis.com/css2?family={family_param}:wght@{weights_str}&display=swap"
    font_stack = f"'{font_family}', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

    if fraud:
        pill_bg, pill_fg, pill = FRAUD_BG, FRAUD_COLOR, 'Flagged for fraud'
        headline = 'Your profile is flagged for fraud and is in review'
        intro = ('Your profile is flagged for fraud and is in review by the event administration team. '
                 'Your ticket is <strong>deactivated and not valid for entry</strong> until an administrator verifies and clears this flag.')
        if reasons:
            items = ''.join(f'<li style="margin:4px 0;">{html.escape(r)}</li>' for r in reasons)
            extra = (f'<p style="margin:16px 0 4px;font-weight:600;color:{colors["text"]};font-family:{font_stack};">Why your profile was flagged</p>'
                     f'<ul style="margin:0;padding-left:20px;color:{colors["text"]};font-size:14px;font-family:{font_stack};">{items}</ul>'
                     f'<p style="margin:12px 0 0;font-size:14px;color:{colors["muted"]};font-family:{font_stack};">If this is an error, please contact event organizers with your original transaction receipt.</p>')
        else:
            extra = (f'<p style="margin:16px 0 0;font-size:14px;color:{colors["muted"]};font-family:{font_stack};">'
                     'If this is an error, please contact event organizers with your original transaction receipt.</p>')
    elif pending:
        pill_bg, pill_fg, pill = PENDING_BG, PENDING_COLOR, 'Under review'
        headline = 'We received your registration'
        intro = ('An organizer is reviewing your payment. Your ticket is attached below, but it is '
                 '<strong>not valid for entry until your registration is approved</strong>. '
                 'We will email you again as soon as that happens.')
        if reasons:
            items = ''.join(f'<li style="margin:4px 0;">{html.escape(r)}</li>' for r in reasons)
            extra = (f'<p style="margin:16px 0 4px;font-weight:600;color:{colors["text"]};font-family:{font_stack};">Why it needs a check</p>'
                     f'<ul style="margin:0;padding-left:20px;color:{colors["text"]};font-size:14px;font-family:{font_stack};">{items}</ul>')
        else:
            extra = f'<p style="margin:16px 0 0;font-size:14px;color:{colors["text"]};font-family:{font_stack};">An organizer will check your payment proof shortly.</p>'
    else:
        pill_bg, pill_fg, pill = OK_BG, OK_COLOR, 'Confirmed'
        headline = "You're registered"
        intro = 'Your registration is confirmed and your ticket is ready. It is attached to this email.'
        extra = (f'<p style="margin:16px 0 4px;font-weight:600;color:{colors["text"]};font-family:{font_stack};">At the event</p>'
                 f'<p style="margin:0;font-size:14px;color:{colors["text"]};font-family:{font_stack};">Show the QR code on your ticket at the entrance, '
                 'either printed or on your phone. Each ticket can be scanned once.</p>')

    banner_html = ''
    event_title = esc(event['title'])
    event_date = esc(event.get('date'))
    if has_banner:
        banner_html = (
            f'<tr><td style="padding:0;margin:0;line-height:0;background:#000000;text-align:center;">'
            f'<img src="cid:banner" alt="{event_title}" width="600" '
            f'style="display:block;width:100%;max-width:600px;height:auto;border:0;margin:0 auto;">'
            f'</td></tr>'
        )

    title_bar = (
        f'<tr><td style="background:{colors["primary"]};padding:22px 32px;'
        f'{"border-top:2px solid rgba(255,255,255,0.15);" if has_banner else ""}">'
        f'<div style="color:{colors["primary_text"]};font-size:22px;font-weight:700;letter-spacing:-0.01em;font-family:{font_stack};">{event_title}</div>'
        f'<div style="color:{colors["primary_text"]};font-size:13px;opacity:0.9;margin-top:4px;font-family:{font_stack};">{event_date}</div>'
        f'</td></tr>'
    )

    image = ''
    if has_image:
        image = (f'<tr><td style="padding:0 32px 24px;">'
                 f'<div style="border:1px solid {colors["border"]};border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.06);">'
                 f'<img src="cid:placard" alt="Your ticket" width="536" '
                 f'style="display:block;width:100%;max-width:536px;height:auto;border:0;">'
                 f'</div></td></tr>')

    rows = ''.join([
        _row('Name', details.get('name'), colors, font_stack),
        _row('Roll number', details.get('roll_number'), colors, font_stack),
        _row('Ticket ID', details.get('ticket_id'), colors, font_stack),
        _row('Department', details.get('dept_name'), colors, font_stack),
        _row('College', details.get('college_name'), colors, font_stack),
        _row('Date', event.get('date'), colors, font_stack),
    ])
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(event['title'])}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{font_url}" rel="stylesheet">
<style>
@import url('{font_url}');
body, table, td, p, h1, span, div {{
    font-family: {font_stack} !important;
}}
</style>
</head>
<body style="margin:0;padding:0;background:{colors['bg']};font-family:{font_stack};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{colors['bg']};padding:24px 12px;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;background:{colors['surface']};border-radius:12px;overflow:hidden;border:1px solid {colors['border']};">
{banner_html}
{title_bar}
<tr><td style="padding:28px 32px 8px;">
<span style="display:inline-block;background:{pill_bg};color:{pill_fg};font-size:12px;font-weight:700;padding:4px 10px;border-radius:999px;font-family:{font_stack};">{pill}</span>
<h1 style="margin:14px 0 8px;font-size:22px;color:{colors['text']};font-family:{font_stack};">{headline}</h1>
<p style="margin:0 0 4px;font-size:15px;line-height:1.5;color:{colors['text']};font-family:{font_stack};">Hi {esc(details.get('name')) or 'there'},</p>
<p style="margin:8px 0 0;font-size:15px;line-height:1.5;color:{colors['text']};font-family:{font_stack};">{intro}</p>
{extra}
</td></tr>
<tr><td style="padding:16px 32px 20px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid {colors['border']};">{rows}</table>
</td></tr>
{image}
<tr><td style="padding:0 32px 28px;font-size:12px;color:{colors['muted']};font-family:{font_stack};">Sent by the {esc(event['title'])} organizers. Please keep this email until the event.</td></tr>
</table>
</td></tr></table>
</body></html>'''


def build_registration_email(*, sender, to_email, event, colors, details, placard_path, pending=False, fraud=False, font=None, banner_path=None):
    """Return an EmailMessage with text + HTML bodies and the ticket inline and attached."""
    event = dict(event, title=_one_line(event.get('title')) or 'the event')
    reasons = _reasons(details.get('review_reason')) if (pending or fraud) else []

    banner_bytes = None
    if banner_path:
        try:
            with open(banner_path, 'rb') as f:
                banner_bytes = f.read()
        except (OSError, TypeError) as e:
            print(f"Error reading banner for email: {e}")

    image_bytes = None
    try:
        with open(placard_path, 'rb') as f:
            image_bytes = f.read()
    except (OSError, TypeError) as e:
        print(f"Error reading placard for email: {e}")

    msg = EmailMessage()
    msg['From'] = formataddr((event['title'], sender))
    msg['To'] = to_email
    if fraud:
        msg['Subject'] = f"ALERT: Your profile for {event['title']} is flagged for fraud and is in review"
    elif pending:
        msg['Subject'] = (f"We received your registration for {event['title']} (under review)")
    else:
        msg['Subject'] = f"Your ticket for {event['title']}"
    msg.set_content(_plain(event, details, pending, reasons, fraud=fraud))
    msg.add_alternative(_html(event, details, colors, pending, reasons, image_bytes is not None,
                              fraud=fraud, font=font, has_banner=banner_bytes is not None), subtype='html')

    html_part = msg.get_payload()[1]
    if banner_bytes is not None:
        html_part.add_related(banner_bytes, 'image', 'jpeg', cid='<banner>')
    if image_bytes is not None:
        html_part.add_related(image_bytes, 'image', 'jpeg', cid='<placard>')
        roll = re.sub(r'[^A-Za-z0-9_-]', '', str(details.get('roll_number') or 'ticket'))
        msg.add_attachment(image_bytes, maintype='image', subtype='jpeg', filename=f'ticket-{roll}.jpg')
    return msg
