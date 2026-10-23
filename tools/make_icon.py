"""Generate the app icon (app/static/icon.svg + app/static/favicon.ico).

The icon is defined once, as a list of shapes in a 256x256 unit coordinate
system (SHAPES). Both the SVG writer and the rasterizer read that same list,
so changing the icon means editing SHAPES and re-running this script:

  python tools/make_icon.py          # regenerate both files
  python tools/make_icon.py --check  # exit 0 if committed files are up to date

Only the standard library is used. Output is deterministic.
"""
import argparse
import math
import struct
import sys
import zlib
from pathlib import Path

SIZES: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)
ACCENT = "#2459d6"
WHITE = "#ffffff"
SHADE = "#1a44a8"  # slightly darker accent for the book spine

UNITS = 256  # design coordinate system is UNITS x UNITS
SUPERSAMPLE = 4  # samples per pixel per axis (4x4 = 16 samples)

# Shape kinds:
#   ("rrect", (x0, y0, x1, y1), radius, color)       rounded rectangle (SDF)
#   ("poly", ((x, y), ...), color)                   even-odd filled polygon
#   ("line", ((x, y), ...), width, color)            thick polyline, round caps/joins
# Later shapes are composited over earlier ones (source-over).
SHAPES = (
    # Background tile filling the canvas.
    ("rrect", (0, 0, 256, 256), 56, ACCENT),
    # Open ledger: two slightly tilted pages meeting at the spine.
    ("poly", ((28, 156), (123, 168), (123, 228), (28, 216)), WHITE),
    ("poly", ((133, 168), (228, 156), (228, 216), (133, 228)), WHITE),
    ("line", ((128, 170), (128, 226)), 8, SHADE),
    # Won sign above the book: a bold W and two horizontal bars.
    ("line", ((68, 36), (98, 126), (128, 56), (158, 126), (188, 36)), 22, WHITE),
    ("line", ((50, 72), (206, 72)), 16, WHITE),
    ("line", ((50, 104), (206, 104)), 16, WHITE),
)


# ---------------------------------------------------------------- helpers

def _rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _num(v) -> str:
    """Format a coordinate compactly and deterministically."""
    if float(v).is_integer():
        return str(int(v))
    return f"{v:.3f}".rstrip("0").rstrip(".")


def _bbox(shape) -> tuple[float, float, float, float]:
    kind = shape[0]
    if kind == "rrect":
        return shape[1]
    pts = shape[1]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    pad = shape[2] / 2 if kind == "line" else 0
    return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad


def _inside_fn(shape):
    """Return a predicate f(x, y) -> bool for a point in design units."""
    kind = shape[0]
    if kind == "rrect":
        x0, y0, x1, y1 = shape[1]
        r = shape[2]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        hx, hy = (x1 - x0) / 2 - r, (y1 - y0) / 2 - r

        def f(x, y):
            qx = abs(x - cx) - hx
            qy = abs(y - cy) - hy
            ox, oy = max(qx, 0.0), max(qy, 0.0)
            d = math.hypot(ox, oy) + min(max(qx, qy), 0.0) - r
            return d <= 0.0
        return f

    if kind == "poly":
        pts = shape[1]
        edges = [(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]

        def f(x, y):
            inside = False
            for (ax, ay), (bx, by) in edges:
                if (ay > y) != (by > y):
                    xi = ax + (y - ay) * (bx - ax) / (by - ay)
                    if x < xi:
                        inside = not inside
            return inside
        return f

    if kind == "line":
        pts = shape[1]
        r2 = (shape[2] / 2) ** 2
        segs = []
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            dx, dy = bx - ax, by - ay
            segs.append((ax, ay, dx, dy, dx * dx + dy * dy))

        def f(x, y):
            for ax, ay, dx, dy, ll in segs:
                t = 0.0 if ll == 0 else ((x - ax) * dx + (y - ay) * dy) / ll
                t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
                ex = x - (ax + t * dx)
                ey = y - (ay + t * dy)
                if ex * ex + ey * ey <= r2:
                    return True
            return False
        return f

    raise ValueError(f"unknown shape kind: {kind}")


# ---------------------------------------------------------------- SVG

def svg() -> str:
    """Return the icon as SVG text (viewBox 0 0 256 256)."""
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {UNITS} {UNITS}" '
        f'width="{UNITS}" height="{UNITS}">'
    ]
    for shape in SHAPES:
        kind = shape[0]
        if kind == "rrect":
            x0, y0, x1, y1 = shape[1]
            out.append(
                f'  <rect x="{_num(x0)}" y="{_num(y0)}" width="{_num(x1 - x0)}" '
                f'height="{_num(y1 - y0)}" rx="{_num(shape[2])}" fill="{shape[3]}"/>'
            )
        elif kind == "poly":
            d = "M" + " L".join(f"{_num(x)} {_num(y)}" for x, y in shape[1]) + " Z"
            out.append(f'  <path d="{d}" fill="{shape[2]}" fill-rule="evenodd"/>')
        elif kind == "line":
            d = "M" + " L".join(f"{_num(x)} {_num(y)}" for x, y in shape[1])
            out.append(
                f'  <path d="{d}" fill="none" stroke="{shape[3]}" '
                f'stroke-width="{_num(shape[2])}" stroke-linecap="round" '
                f'stroke-linejoin="round"/>'
            )
        else:
            raise ValueError(f"unknown shape kind: {kind}")
    out.append("</svg>")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- raster

def render(size: int) -> bytes:
    """Rasterize SHAPES to size x size straight RGBA (8-bit, rows top-down)."""
    n = SUPERSAMPLE
    scale = UNITS / size
    nsamples = n * n
    # Straight-alpha float buffers.
    ca = [0.0] * (size * size)
    cr = [0.0] * (size * size)
    cg = [0.0] * (size * size)
    cb = [0.0] * (size * size)
    offsets = [(i + 0.5) / n for i in range(n)]

    for shape in SHAPES:
        inside = _inside_fn(shape)
        color = shape[-1]
        sr, sg, sb = (v / 255 for v in _rgb(color))
        bx0, by0, bx1, by1 = _bbox(shape)
        px0 = max(0, int(math.floor(bx0 / scale)))
        py0 = max(0, int(math.floor(by0 / scale)))
        px1 = min(size, int(math.ceil(bx1 / scale)))
        py1 = min(size, int(math.ceil(by1 / scale)))
        for py in range(py0, py1):
            sys_ = [(py + o) * scale for o in offsets]
            row = py * size
            for px in range(px0, px1):
                sxs = [(px + o) * scale for o in offsets]
                hits = 0
                for y in sys_:
                    for x in sxs:
                        if inside(x, y):
                            hits += 1
                if not hits:
                    continue
                a = hits / nsamples
                i = row + px
                da = ca[i]
                oa = a + da * (1.0 - a)
                k = da * (1.0 - a)
                cr[i] = (sr * a + cr[i] * k) / oa
                cg[i] = (sg * a + cg[i] * k) / oa
                cb[i] = (sb * a + cb[i] * k) / oa
                ca[i] = oa

    out = bytearray(size * size * 4)
    for i in range(size * size):
        a = ca[i]
        if a <= 0.0:
            continue  # fully transparent stays (0, 0, 0, 0)
        j = i * 4
        out[j] = int(cr[i] * 255 + 0.5)
        out[j + 1] = int(cg[i] * 255 + 0.5)
        out[j + 2] = int(cb[i] * 255 + 0.5)
        out[j + 3] = int(a * 255 + 0.5)
    return bytes(out)


# ---------------------------------------------------------------- encoders

def _chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def png(size: int, rgba: bytes) -> bytes:
    """Encode size x size RGBA as PNG (color type 6, 8-bit)."""
    stride = size * 4
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filter: none
        raw += rgba[y * stride:(y + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )


def _bmp_dib(size: int, rgba: bytes) -> bytes:
    """32bpp BMP DIB for an ICO entry: header, bottom-up BGRA, AND mask."""
    mask_row = ((size + 31) // 32) * 4
    xor = bytearray()
    mask = bytearray()
    for y in range(size - 1, -1, -1):
        row = bytearray(mask_row)
        for x in range(size):
            j = (y * size + x) * 4
            r, g, b, a = rgba[j], rgba[j + 1], rgba[j + 2], rgba[j + 3]
            xor += bytes((b, g, r, a))
            if a == 0:
                row[x >> 3] |= 0x80 >> (x & 7)
        mask += row
    header = struct.pack(
        "<IiiHHIIiiII",
        40, size, size * 2, 1, 32, 0, len(xor) + len(mask), 0, 0, 0, 0,
    )
    return header + bytes(xor) + bytes(mask)


def ico(images: dict[int, bytes]) -> bytes:
    """Build an ICO from {size: rgba}. Sizes < 256 use BMP DIBs, 256 uses PNG."""
    sizes = sorted(images)
    blobs = []
    for s in sizes:
        if s >= 256:
            blobs.append(png(s, images[s]))
        else:
            blobs.append(_bmp_dib(s, images[s]))
    out = bytearray(struct.pack("<HHH", 0, 1, len(sizes)))
    offset = 6 + 16 * len(sizes)
    for s, blob in zip(sizes, blobs):
        dim = 0 if s >= 256 else s
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    for blob in blobs:
        out += blob
    return bytes(out)


# ---------------------------------------------------------------- CLI

def _outputs() -> dict[Path, bytes]:
    static = Path(__file__).resolve().parent.parent / "app" / "static"
    return {
        static / "icon.svg": svg().encode("utf-8"),
        static / "favicon.ico": ico({s: render(s) for s in SIZES}),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generate the app icon (SVG + ICO).")
    ap.add_argument("--check", action="store_true",
                    help="write nothing; exit 0 if files match generated output, else 1")
    args = ap.parse_args(argv)
    outputs = _outputs()
    if args.check:
        stale = [p for p, data in outputs.items()
                 if not p.is_file() or p.read_bytes() != data]
        for p in stale:
            print(f"out of date: {p}", file=sys.stderr)
        return 1 if stale else 0
    for p, data in outputs.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        print(f"wrote {p} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
