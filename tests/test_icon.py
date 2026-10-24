"""App icon: tools/make_icon.py generator (SVG + ICO), committed icon files, window title and icon wiring.

The generator is a standalone script (not a package) and is loaded by file path.
Only 16 and 32 px are rendered here, except test_main_check_matches_committed_files (full render).
"""
import importlib.util
import re
import struct
import sys
import time
import types
import zlib
from html.parser import HTMLParser
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "make_icon.py"
STATIC = ROOT / "app" / "static"
ICO_FILE = STATIC / "favicon.ico"
SVG_FILE = STATIC / "icon.svg"
INDEX = STATIC / "index.html"
SPEC = ROOT / "asset_manager.spec"

EXPECTED_SIZES = (16, 24, 32, 48, 64, 128, 256)
ACCENT_RGB = (36, 89, 214)
PNG_SIG = b"\x89PNG\r\n\x1a\n"
SVG_NS = "{http://www.w3.org/2000/svg}"


def load_tool():
    spec = importlib.util.spec_from_file_location("make_icon", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mi():
    return load_tool()


@pytest.fixture(scope="module")
def rgba16(mi):
    return mi.render(16)


@pytest.fixture(scope="module")
def rgba32(mi):
    return mi.render(32)


# ---------- helpers ----------

def pixel(rgba, size, x, y):
    i = (y * size + x) * 4
    return tuple(rgba[i:i + 4])


def parse_png(data):
    """Return (ihdr dict, raw decompressed IDAT bytes)."""
    assert data[:8] == PNG_SIG
    pos = 8
    ihdr = None
    idat = b""
    while pos < len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            w, h, depth, color, comp, filt, inter = struct.unpack(">IIBBBBB", body)
            ihdr = dict(width=w, height=h, depth=depth, color=color, comp=comp, filter=filt, interlace=inter)
        elif ctype == b"IDAT":
            idat += body
        elif ctype == b"IEND":
            break
        pos += 12 + length
    assert ihdr is not None, "IHDR missing"
    return ihdr, zlib.decompress(idat)


def check_png(data, size, rgba=None):
    ihdr, raw = parse_png(data)
    assert ihdr["width"] == size and ihdr["height"] == size
    assert ihdr["depth"] == 8
    assert ihdr["color"] == 6
    stride = size * 4
    assert len(raw) == size * (stride + 1)
    filters = [raw[r * (stride + 1)] for r in range(size)]
    if rgba is not None and all(f == 0 for f in filters):
        pixels = b"".join(raw[r * (stride + 1) + 1:(r + 1) * (stride + 1)] for r in range(size))
        assert pixels == rgba


def mask_row_bytes(size):
    return ((size + 31) // 32) * 4


def parse_ico(data):
    """Validate ICO structure (criterion 6 rules) and return list of (size, entry dict, image bytes)."""
    reserved, typ, count = struct.unpack("<HHH", data[:6])
    assert reserved == 0
    assert typ == 1
    out = []
    for i in range(count):
        w, h, colors, res, planes, bits, nbytes, offset = struct.unpack(
            "<BBBBHHII", data[6 + 16 * i:6 + 16 * (i + 1)])
        assert planes == 1
        assert bits == 32
        assert w == h
        size = w or 256
        assert offset + nbytes <= len(data), f"entry {size} out of file bounds"
        img = data[offset:offset + nbytes]
        if size < 256:
            assert w == size
            bi = struct.unpack("<IiiHHIIiiII", img[:40])
            assert bi[0] == 40
            assert bi[1] == size
            assert bi[2] == 2 * size
            assert bi[3] == 1
            assert bi[4] == 32
            assert bi[5] == 0
            assert nbytes == 40 + size * size * 4 + mask_row_bytes(size) * size
        else:
            assert w == 0 and h == 0
            assert img[:8] == PNG_SIG
            ihdr, _ = parse_png(img)
            assert ihdr["width"] == 256 and ihdr["height"] == 256
        out.append((size, dict(nbytes=nbytes, offset=offset), img))
    return count, out


def bmp_to_rgba(img, size):
    """BMP DIB entry -> (RGBA top-down bytes, AND mask bit grid top-down)."""
    xor = img[40:40 + size * size * 4]
    rows = []
    for y in range(size):
        src = xor[(size - 1 - y) * size * 4:(size - y) * size * 4]
        row = bytearray()
        for x in range(size):
            b, g, r, a = src[x * 4:x * 4 + 4]
            row += bytes((r, g, b, a))
        rows.append(bytes(row))
    rb = mask_row_bytes(size)
    mask_data = img[40 + size * size * 4:]
    mask = []
    for y in range(size):
        row = mask_data[(size - 1 - y) * rb:(size - y) * rb]
        mask.append([(row[x // 8] >> (7 - x % 8)) & 1 for x in range(size)])
    return b"".join(rows), mask


@pytest.fixture(scope="module")
def ico_entries():
    data = ICO_FILE.read_bytes()
    count, entries = parse_ico(data)
    return data, count, entries


# ---------- 1. module constants / no side effects ----------

def test_import_has_no_side_effects():
    def snapshot():
        return {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in (ICO_FILE, SVG_FILE) if p.exists()}

    before = snapshot()
    names_before = sorted(p.name for p in STATIC.iterdir())
    load_tool()
    assert snapshot() == before
    assert sorted(p.name for p in STATIC.iterdir()) == names_before


def test_constants(mi):
    assert tuple(mi.SIZES) == EXPECTED_SIZES
    assert mi.ACCENT == "#2459d6"


# ---------- 2-4. render ----------

@pytest.mark.parametrize("size", [16, 32])
def test_render_length_and_type(mi, rgba16, rgba32, size):
    rgba = rgba16 if size == 16 else rgba32
    assert isinstance(rgba, bytes)
    assert len(rgba) == size * size * 4


@pytest.mark.parametrize("size", [16, 32])
def test_render_corners_transparent_center_opaque(rgba16, rgba32, size):
    rgba = rgba16 if size == 16 else rgba32
    last = size - 1
    for x, y in ((0, 0), (last, 0), (0, last), (last, last)):
        assert pixel(rgba, size, x, y)[3] == 0, f"corner ({x},{y}) not fully transparent at {size}px"
    c = size // 2
    assert pixel(rgba, size, c, c)[3] == 255


def test_render_deterministic(mi, rgba32):
    assert mi.render(32) == mi.render(32)
    assert mi.render(32) == rgba32


def test_render_32_under_two_seconds(mi):
    t0 = time.perf_counter()
    mi.render(32)
    assert time.perf_counter() - t0 < 2.0


def test_render_has_accent_and_white_pixels(rgba32):
    px = {tuple(rgba32[i:i + 4]) for i in range(0, len(rgba32), 4)}
    assert ACCENT_RGB + (255,) in px, "no opaque accent #2459d6 pixel"
    assert (255, 255, 255, 255) in px, "no opaque white pixel"


# ---------- 5. png ----------

@pytest.mark.parametrize("size", [16, 32])
def test_png_structure_and_roundtrip(mi, rgba16, rgba32, size):
    rgba = rgba16 if size == 16 else rgba32
    data = mi.png(size, rgba)
    assert data.startswith(PNG_SIG)
    check_png(data, size, rgba)


# ---------- 6. committed favicon.ico structure ----------

def test_ico_header(ico_entries):
    data, count, _ = ico_entries
    reserved, typ, cnt = struct.unpack("<HHH", data[:6])
    assert (reserved, typ, cnt) == (0, 1, 7)
    assert count == 7


def test_ico_entries_sorted_sizes(ico_entries):
    _, _, entries = ico_entries
    assert tuple(s for s, _, _ in entries) == EXPECTED_SIZES


def test_ico_256_entry_width_height_zero(ico_entries):
    data, count, _ = ico_entries
    for i in range(count):
        w, h = data[6 + 16 * i], data[7 + 16 * i]
        if w == 0:
            assert h == 0
            break
    else:
        pytest.fail("no 256px entry (width byte 0)")


@pytest.mark.parametrize("size", [24, 48])
def test_ico_mask_padding_non_multiple_of_32(ico_entries, size):
    _, _, entries = ico_entries
    nbytes = next(e["nbytes"] for s, e, _ in entries if s == size)
    rb = ((size + 31) // 32) * 4
    assert rb == 4 if size == 24 else rb == 8
    assert nbytes == 40 + size * size * 4 + rb * size


def test_ico_256_is_png(ico_entries):
    _, _, entries = ico_entries
    img = next(img for s, _, img in entries if s == 256)
    check_png(img, 256)


# ---------- 7. ICO pixels match render ----------

@pytest.mark.parametrize("size", [16, 32])
def test_ico_bmp_pixels_match_render(ico_entries, rgba16, rgba32, size):
    _, _, entries = ico_entries
    rgba = rgba16 if size == 16 else rgba32
    img = next(img for s, _, img in entries if s == size)
    got, mask = bmp_to_rgba(img, size)
    assert got == rgba
    for y in range(size):
        for x in range(size):
            expected = 1 if pixel(rgba, size, x, y)[3] == 0 else 0
            assert mask[y][x] == expected, f"AND mask bit at ({x},{y}) size {size}"


# ---------- 8. ico() ----------

def test_ico_function_two_entries(mi, rgba16, rgba32):
    data = mi.ico({16: rgba16, 32: rgba32})
    count, entries = parse_ico(data)
    assert count == 2
    assert [s for s, _, _ in entries] == [16, 32]
    for size, _, img in entries:
        got, _ = bmp_to_rgba(img, size)
        assert got == (rgba16 if size == 16 else rgba32)


# ---------- 9. icon.svg ----------

def test_svg_file_matches_generator(mi):
    assert SVG_FILE.read_bytes().decode("utf-8") == mi.svg()


def test_svg_is_safe_and_well_formed(mi):
    text = mi.svg()
    root = ET.fromstring(text)
    assert root.tag == f"{SVG_NS}svg"
    assert root.get("viewBox") == "0 0 256 256"
    for el in root.iter():
        local = el.tag.split("}")[-1]
        assert local not in ("script", "text"), f"forbidden element <{local}>"
        for attr in el.attrib:
            assert attr.split("}")[-1] != "href", f"forbidden attribute {attr}"
    assert "#2459d6" in text.lower()


# ---------- 10. main --check (slow: full render) ----------

def test_main_check_matches_committed_files(mi):
    before = {p: p.read_bytes() for p in (ICO_FILE, SVG_FILE)}
    t0 = time.perf_counter()
    assert mi.main(["--check"]) == 0
    assert time.perf_counter() - t0 < 60
    assert {p: p.read_bytes() for p in (ICO_FILE, SVG_FILE)} == before


# ---------- 11-13. app config / main ----------

def test_config_icon_file():
    from app import config
    assert config.icon_file() == config.static_dir() / "favicon.ico"
    assert config.icon_file().is_file()


def test_window_title():
    import app
    from app import main as app_main
    title = app_main.window_title()
    assert title == "v" + app.__version__
    assert title == "v0.2.0"
    assert "개인 자산 관리" not in title


def test_main_uses_title_icon_and_settings(monkeypatch):
    from app import config
    from app import main as app_main

    calls = {"create_window": [], "start": []}
    fake = types.ModuleType("webview")
    fake.settings = {}
    fake.create_window = lambda *a, **k: calls["create_window"].append((a, k))
    fake.start = lambda *a, **k: calls["start"].append((a, k))
    monkeypatch.setitem(sys.modules, "webview", fake)

    port = app_main.free_port()
    assert app_main.main(["--port", str(port)]) == 0

    assert len(calls["create_window"]) == 1
    args, _ = calls["create_window"][0]
    assert args[0] == app_main.window_title()
    assert args[1] == f"http://127.0.0.1:{port}"
    assert len(calls["start"]) == 1
    _, kwargs = calls["start"][0]
    assert kwargs.get("icon") == str(config.icon_file())
    assert fake.settings.get("ALLOW_DOWNLOADS") is True


# ---------- 14. served by the app ----------

def test_favicon_served(client):
    r = client.get("/favicon.ico")
    assert r.status_code == 200
    assert r.content == ICO_FILE.read_bytes()


def test_icon_svg_served(client):
    r = client.get("/icon.svg")
    assert r.status_code == 200
    assert r.content == SVG_FILE.read_bytes()
    assert r.headers["content-type"].startswith("image/")


# ---------- 15. index.html links ----------

class _HeadLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_head = False
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self.in_head = True
        elif tag == "link" and self.in_head:
            self.links.append({k.lower(): (v or "") for k, v in attrs})

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False


def test_index_html_icon_links():
    html = INDEX.read_text(encoding="utf-8")
    p = _HeadLinks()
    p.feed(html)
    rels = lambda l: l.get("rel", "").lower().split()
    assert any("icon" in rels(l) and l.get("href") == "/favicon.ico" for l in p.links), \
        "missing <link rel=icon href=/favicon.ico> in <head>"
    assert any(l.get("href") == "/icon.svg" and l.get("type") == "image/svg+xml" for l in p.links), \
        "missing <link href=/icon.svg type=image/svg+xml> in <head>"
    assert re.search(r"<title>\s*개인 자산 관리\s*</title>", html)


# ---------- 16. PyInstaller spec ----------

def _call_body(text, name):
    m = re.search(rf"\b{name}\s*\(", text)
    assert m, f"{name}( not found"
    depth, i = 1, m.end()
    while depth and i < len(text):
        depth += {"(": 1, ")": -1}.get(text[i], 0)
        i += 1
    return text[m.end():i - 1]


def test_spec_exe_icon():
    body = _call_body(SPEC.read_text(encoding="utf-8"), "EXE")
    assert re.search(r"""\bicon\s*=\s*["']app/static/favicon\.ico["']""", body)
