"""Event theming: validated palette + banner loader, and the `from-banner` CLI.

Only brand/layout colours are themable. Status colours (confirmed / pending /
rejected, gate check-in screens) are fixed in templates/_theme_head.html so a
theme can never turn "valid" into an ambiguous colour at the gate.

Usage:
    python theme.py from-banner theme/banner.jpg      # writes theme/theme.json
"""
import argparse
import colorsys
import copy
import json
import os
import re
import sys

from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
THEME_PATH = os.path.join(BASE_DIR, 'theme', 'theme.json')
BANNER_OUT_REL = os.path.join('static', 'theme', 'banner.jpg')  # generated, never edited by hand
BANNER_MAX_WIDTH = 1584
BANNER_ASPECT = (4, 1)
MIN_TEXT_CONTRAST = 4.5

COLOR_KEYS = ('bg', 'surface', 'text', 'muted', 'border', 'primary', 'primary_text')
FOCUS_VALUES = ('center', 'top', 'bottom', 'left', 'right')
HEX_RE = re.compile(r'^#[0-9A-Fa-f]{6}$')
FONT_RE = re.compile(r'^[A-Za-z0-9 ]{1,40}$')

DEFAULT_THEME = {
    'banner': None,
    'banner_focus': 'center',
    'colors': {
        'bg': '#F4F6F8',
        'surface': '#FFFFFF',
        'text': '#111827',
        'muted': '#5B6472',
        'border': '#D9DEE5',
        'primary': '#1D4ED8',
        'primary_text': '#FFFFFF',
    },
    'font': {'family': 'Inter', 'weights': [400, 600]},
}


class ThemeError(ValueError):
    """Raised when a theme file is malformed or fails a contrast check."""


# ── colour maths ─────────────────────────────────────────────────────────────
def _rgb(hex_color):
    h = hex_color.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return '#{:02X}{:02X}{:02X}'.format(*(max(0, min(255, round(c))) for c in rgb))


def relative_luminance(hex_color):
    def chan(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg, bg):
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return round((hi + 0.05) / (lo + 0.05), 2)


def _mix(a, b, weight_b):
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(x * (1 - weight_b) + y * weight_b for x, y in zip(ra, rb)))


def _hls(hex_color):
    return colorsys.rgb_to_hls(*(c / 255 for c in _rgb(hex_color)))


def _from_hls(h, l, s):
    return _hex(tuple(c * 255 for c in colorsys.hls_to_rgb(h, max(0, min(1, l)), max(0, min(1, s)))))


# ── validation / loading ─────────────────────────────────────────────────────
def validate_theme(data):
    """Raise ThemeError unless `data` matches the schema and passes contrast checks."""
    if not isinstance(data, dict):
        raise ThemeError('theme must be a JSON object')
    allowed = {'banner', 'banner_focus', 'colors', 'font'}
    if set(data) - allowed:
        raise ThemeError(f'unknown keys: {sorted(set(data) - allowed)}')

    colors = data.get('colors')
    if not isinstance(colors, dict):
        raise ThemeError('colors must be an object')
    if set(colors) != set(COLOR_KEYS):
        raise ThemeError(f'colors must contain exactly {list(COLOR_KEYS)}')
    for key, value in colors.items():
        if not isinstance(value, str) or not HEX_RE.match(value):
            raise ThemeError(f'colors.{key} must be a #RRGGBB hex value')

    banner = data.get('banner')
    if banner is not None:
        if (not isinstance(banner, str) or os.path.isabs(banner) or '..' in banner
                or not banner.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))):
            raise ThemeError('banner must be null or a relative .jpg/.png/.webp path')
    if data.get('banner_focus', 'center') not in FOCUS_VALUES:
        raise ThemeError(f'banner_focus must be one of {FOCUS_VALUES}')

    font = data.get('font')
    if not isinstance(font, dict) or set(font) != {'family', 'weights'}:
        raise ThemeError('font must have exactly family and weights')
    if not isinstance(font['family'], str) or not FONT_RE.match(font['family']):
        raise ThemeError('font.family may only contain letters, digits and spaces')
    weights = font['weights']
    if (not isinstance(weights, list) or not weights
            or not all(isinstance(w, int) and not isinstance(w, bool) and 100 <= w <= 900 and w % 100 == 0
                       for w in weights)):
        raise ThemeError('font.weights must be a list of ints like 400, 600')

    checks = [
        ('text', 'surface'), ('text', 'bg'), ('muted', 'surface'), ('primary_text', 'primary'),
    ]
    for fg, bg in checks:
        ratio = contrast_ratio(colors[fg], colors[bg])
        if ratio < MIN_TEXT_CONTRAST:
            raise ThemeError(f'contrast too low: {fg} on {bg} is {ratio}:1 (needs {MIN_TEXT_CONTRAST}:1)')


def load_theme(path=THEME_PATH):
    """Load and validate the theme file; on any problem log why and return the default."""
    if not os.path.exists(path):
        return copy.deepcopy(DEFAULT_THEME)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        validate_theme(data)
        data.setdefault('banner_focus', 'center')
        return data
    except (OSError, ValueError) as e:  # JSONDecodeError and ThemeError are ValueErrors
        print(f"[WARN] Theme file {path} ignored, using default theme: {e}")
        return copy.deepcopy(DEFAULT_THEME)


# ── banner ───────────────────────────────────────────────────────────────────
def process_banner(src, dest):
    """Validate and re-encode the organizer's banner to a capped-size JPEG. Returns True on success."""
    try:
        with Image.open(src) as probe:
            probe.verify()
        with Image.open(src) as img:
            img = img.convert('RGB')
            if img.width > BANNER_MAX_WIDTH:
                ratio = BANNER_MAX_WIDTH / img.width
                img = img.resize((BANNER_MAX_WIDTH, max(1, round(img.height * ratio))), Image.Resampling.LANCZOS)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            img.save(dest, 'JPEG', quality=85)
        return True
    except Exception as e:
        print(f"[WARN] Banner {src} ignored: {e}")
        if os.path.exists(dest):
            try:
                os.remove(dest)
            except OSError:
                pass
        return False


def prepare_banner(theme_data, dest=None):
    """Process theme['banner'] into the static dir. Returns the static-relative URL path or None."""
    banner = theme_data.get('banner')
    if not banner:
        return None
    dest = dest or os.path.join(BASE_DIR, BANNER_OUT_REL)
    if process_banner(os.path.join(BASE_DIR, banner), dest):
        return 'theme/banner.jpg'
    return None


# ── palette extraction ───────────────────────────────────────────────────────
def _best_button_text(primary):
    white_ratio = contrast_ratio('#FFFFFF', primary)
    ink = '#111827'
    return ('#FFFFFF', white_ratio) if white_ratio >= contrast_ratio(ink, primary) else (ink, contrast_ratio(ink, primary))


def palette_from_banner(path):
    """Deterministically derive a valid 7-colour palette from a banner image."""
    with Image.open(path) as img:
        img = img.convert('RGB')
        img.thumbnail((200, 200))
        quant = img.quantize(colors=5)
        pal = quant.getpalette()[:15]
        counts = dict((idx, n) for n, idx in quant.getcolors())
    candidates = []
    for idx in range(5):
        rgb = tuple(pal[idx * 3: idx * 3 + 3])
        if idx in counts and len(rgb) == 3:
            h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
            candidates.append((s * (1 - abs(l - 0.45)), h, l, s))
    candidates.sort(reverse=True)  # most saturated, mid-lightness first
    _, h, l, s = candidates[0] if candidates else (0, 0.6, 0.4, 0.5)
    s = max(s, 0.35) if s > 0.05 else s  # keep genuinely grey banners grey

    # Walk lightness down until the primary supports readable button text
    primary = _from_hls(h, l, s)
    for _ in range(40):
        text_on_primary, ratio = _best_button_text(primary)
        if ratio >= MIN_TEXT_CONTRAST:
            break
        l -= 0.02
        primary = _from_hls(h, l, s)
    text_on_primary, _ = _best_button_text(primary)

    ink_h = h if s > 0.05 else 0.6
    colors = {
        'bg': _mix(primary, '#FFFFFF', 0.95),
        'surface': '#FFFFFF',
        'text': _from_hls(ink_h, 0.09, min(s, 0.35)),
        'muted': None,
        'border': _mix(primary, '#FFFFFF', 0.82),
        'primary': primary,
        'primary_text': text_on_primary,
    }
    ml = 0.42
    muted = _from_hls(ink_h, ml, 0.12)
    while ml > 0.05 and min(contrast_ratio(muted, colors['surface']), contrast_ratio(muted, colors['bg'])) < MIN_TEXT_CONTRAST:
        ml -= 0.02
        muted = _from_hls(ink_h, ml, 0.12)
    colors['muted'] = muted
    return colors


def build_theme_from_banner(path):
    data = copy.deepcopy(DEFAULT_THEME)
    data['banner'] = 'theme/banner.jpg'
    data['colors'] = palette_from_banner(path)
    validate_theme(data)
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description='Event theme tools')
    sub = parser.add_subparsers(dest='command', required=True)
    fb = sub.add_parser('from-banner', help='derive theme/theme.json from a banner image')
    fb.add_argument('banner')
    fb.add_argument('--out', default=THEME_PATH)
    args = parser.parse_args(argv)

    if args.command == 'from-banner':
        data = build_theme_from_banner(args.banner)
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print(f"Wrote {args.out}")
        for key, value in data['colors'].items():
            print(f"  {key:<13}{value}")
        print("Contrast checks passed. Place your banner at theme/banner.jpg (keep key content in the centre 60%).")
    return 0


if __name__ == '__main__':
    sys.exit(main())
