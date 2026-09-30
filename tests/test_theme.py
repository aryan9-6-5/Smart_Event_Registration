import copy
import json
import os

import pytest
from PIL import Image

import theme as T


def _good():
    return copy.deepcopy(T.DEFAULT_THEME)


# ── contrast maths ───────────────────────────────────────────────────────────
def test_contrast_ratio_extremes():
    assert round(T.contrast_ratio('#000000', '#FFFFFF'), 1) == 21.0
    assert T.contrast_ratio('#777777', '#777777') == 1.0


def test_default_theme_is_valid():
    T.validate_theme(_good())


# ── validation ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize('bad', ['red', '#12345', '#GGGGGG', '112233', '#1122334455', 12345, None])
def test_rejects_bad_hex(bad):
    data = _good()
    data['colors']['primary'] = bad
    with pytest.raises(T.ThemeError):
        T.validate_theme(data)


def test_rejects_missing_color_key():
    data = _good()
    del data['colors']['muted']
    with pytest.raises(T.ThemeError):
        T.validate_theme(data)


def test_rejects_unknown_keys():
    data = _good()
    data['colors']['ok'] = '#FF8800'  # status colours must never be themable
    with pytest.raises(T.ThemeError):
        T.validate_theme(data)
    data = _good()
    data['extra'] = 1
    with pytest.raises(T.ThemeError):
        T.validate_theme(data)


def test_rejects_low_contrast_text_on_surface():
    data = _good()
    data['colors']['text'] = '#CCCCCC'
    with pytest.raises(T.ThemeError, match='contrast'):
        T.validate_theme(data)


def test_rejects_low_contrast_button_text():
    data = _good()
    data['colors']['primary'] = '#FFE066'  # white text on pale yellow
    data['colors']['primary_text'] = '#FFFFFF'
    with pytest.raises(T.ThemeError, match='contrast'):
        T.validate_theme(data)


@pytest.mark.parametrize('family', ['Inter;}body{display:none', 'a" onload="x', '<script>', ''])
def test_rejects_unsafe_font_family(family):
    data = _good()
    data['font']['family'] = family
    with pytest.raises(T.ThemeError):
        T.validate_theme(data)


def test_rejects_bad_font_weights_and_focus():
    data = _good()
    data['font']['weights'] = [400, 'bold']
    with pytest.raises(T.ThemeError):
        T.validate_theme(data)
    data = _good()
    data['banner_focus'] = 'expression(alert(1))'
    with pytest.raises(T.ThemeError):
        T.validate_theme(data)


# ── loader / fallback ────────────────────────────────────────────────────────
def test_load_theme_missing_file_returns_default(tmp_path):
    assert T.load_theme(str(tmp_path / 'nope.json')) == T.DEFAULT_THEME


def test_load_theme_invalid_json_falls_back(tmp_path, capsys):
    p = tmp_path / 'theme.json'
    p.write_text('{not json')
    assert T.load_theme(str(p)) == T.DEFAULT_THEME
    assert 'theme' in capsys.readouterr().out.lower()


def test_load_theme_low_contrast_falls_back_with_reason(tmp_path, capsys):
    data = _good()
    data['colors']['text'] = '#DDDDDD'
    p = tmp_path / 'theme.json'
    p.write_text(json.dumps(data))
    assert T.load_theme(str(p)) == T.DEFAULT_THEME
    assert 'contrast' in capsys.readouterr().out.lower()


def test_load_theme_valid_custom(tmp_path):
    data = _good()
    data['colors']['primary'] = '#0E7C6B'
    p = tmp_path / 'theme.json'
    p.write_text(json.dumps(data))
    assert T.load_theme(str(p))['colors']['primary'] == '#0E7C6B'


# ── banner processing ────────────────────────────────────────────────────────
def test_process_banner_reencodes_and_caps_width(tmp_path):
    src = tmp_path / 'banner.png'
    Image.new('RGB', (3000, 750), '#2244AA').save(src)
    dest = tmp_path / 'out' / 'banner.jpg'
    assert T.process_banner(str(src), str(dest)) is True
    with Image.open(dest) as img:
        assert img.format == 'JPEG'
        assert img.width <= T.BANNER_MAX_WIDTH


def test_process_banner_rejects_non_image(tmp_path):
    src = tmp_path / 'banner.jpg'
    src.write_text('<html>not an image</html>')
    assert T.process_banner(str(src), str(tmp_path / 'out.jpg')) is False
    assert not os.path.exists(tmp_path / 'out.jpg')


def test_process_banner_missing_file(tmp_path):
    assert T.process_banner(str(tmp_path / 'none.jpg'), str(tmp_path / 'o.jpg')) is False


# ── palette extraction ───────────────────────────────────────────────────────
@pytest.mark.parametrize('color', ['#1D4ED8', '#F4D03F', '#0E7C6B', '#C0392B', '#888888'])
def test_palette_from_banner_always_passes_validation(tmp_path, color):
    src = tmp_path / 'b.png'
    img = Image.new('RGB', (400, 100), '#F3F3F3')
    img.paste(Image.new('RGB', (200, 100), color), (100, 0))
    img.save(src)
    palette = T.palette_from_banner(str(src))
    data = _good()
    data['colors'] = palette
    T.validate_theme(data)


def test_write_theme_from_banner_cli(tmp_path):
    src = tmp_path / 'b.png'
    Image.new('RGB', (400, 100), '#0E7C6B').save(src)
    out = tmp_path / 'theme.json'
    T.main(['from-banner', str(src), '--out', str(out)])
    written = json.loads(out.read_text())
    T.validate_theme(written)
    assert written['banner'] == 'theme/banner.jpg'


def test_prepare_banner_with_jpeg_extension(tmp_path, monkeypatch):
    banner_src = tmp_path / 'banner.jpeg'
    Image.new('RGB', (800, 200), '#FF0000').save(banner_src)
    dest = tmp_path / 'out.jpg'
    
    monkeypatch.setattr(T, 'BASE_DIR', str(tmp_path))
    res = T.prepare_banner({'banner': 'banner.jpeg'}, dest=str(dest))
    assert res == 'theme/banner.jpg'
    assert os.path.exists(str(dest))


def test_prepare_banner_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(T, 'BASE_DIR', str(tmp_path))
    res = T.prepare_banner({'banner': 'non_existent.jpg'}, dest=str(tmp_path / 'out.jpg'))
    assert res is None


def test_prepare_banner_corrupted_file_returns_none(tmp_path, monkeypatch):
    corrupt = tmp_path / 'corrupt.jpg'
    corrupt.write_bytes(b'not an image at all')
    monkeypatch.setattr(T, 'BASE_DIR', str(tmp_path))
    res = T.prepare_banner({'banner': 'corrupt.jpg'}, dest=str(tmp_path / 'out.jpg'))
    assert res is None

