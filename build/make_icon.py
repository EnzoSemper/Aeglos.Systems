"""
Generate AEGLOS Analytics Pro app icon from the official Aeglos Systems logo.
Produces build/icon.icns (macOS) and build/icon.ico (Windows).

The logo is composited onto the app's dark background (#0a0e14) so it
looks correct in both the Finder and the macOS dock.
"""

import os
import struct
import zlib
import sys
import subprocess
import shutil
from pathlib import Path

BUILD_DIR  = Path(__file__).parent
ROOT_DIR   = BUILD_DIR.parent

# Source logo — prefer the 1024×1024 standard for best quality
LOGO_STD   = ROOT_DIR.parent / "Aeglos-OS" / "aeglos_logo.png"
LOGO_WHITE = ROOT_DIR.parent / "Aeglos-OS" / "aeglos_logo_white.png"

# Pick the largest available
def _logo_size(p):
    if not p.exists(): return 0
    try:
        raw = p.read_bytes()
        import struct
        w = struct.unpack(">I", raw[16:20])[0]
        return w
    except Exception:
        return 0

LOGO_SRC = max([LOGO_STD, LOGO_WHITE], key=_logo_size)
if _logo_size(LOGO_SRC) == 0:
    LOGO_SRC = LOGO_STD  # fallback

if not LOGO_SRC.exists():
    # Also check if it was copied locally
    for candidate in [
        ROOT_DIR / "aeglos_logo_white.png",
        ROOT_DIR / "aeglos_logo.png",
        BUILD_DIR / "source_logo.png",
    ]:
        if candidate.exists():
            LOGO_SRC = candidate
            break
    else:
        print(f"ERROR: Logo not found. Checked:\n  {LOGO_WHITE}\n  {LOGO_STD}")
        sys.exit(1)

print(f"Using logo: {LOGO_SRC}")

# ── PNG utilities (no Pillow needed for simple compositing) ──────────────────

def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def _read_png_rgba(path: Path):
    """Read PNG into a flat bytearray of (R,G,B,A) tuples, return (pixels, width, height)."""
    import zlib, struct
    raw = path.read_bytes()
    assert raw[:8] == b'\x89PNG\r\n\x1a\n', "Not a PNG"

    pos = 8
    chunks = {}
    raw_idat = b""
    while pos < len(raw):
        length = struct.unpack(">I", raw[pos:pos+4])[0]
        tag    = raw[pos+4:pos+8]
        data   = raw[pos+8:pos+8+length]
        if tag == b'IHDR':
            w, h, bd, ct = struct.unpack(">IIBB", data[:10])
            chunks['IHDR'] = (w, h, bd, ct)
        elif tag == b'IDAT':
            raw_idat += data
        pos += 12 + length

    w, h, bit_depth, color_type = chunks['IHDR']
    assert bit_depth == 8, f"Only 8-bit depth supported (got {bit_depth})"
    # color_type: 2=RGB, 6=RGBA
    has_alpha = (color_type == 6)
    channels  = 4 if has_alpha else 3

    decompressed = zlib.decompress(raw_idat)
    stride = w * channels + 1  # +1 for filter byte
    assert len(decompressed) == stride * h, f"Data size mismatch"

    pixels = bytearray(w * h * 4)  # always RGBA output
    for y in range(h):
        row_start = y * stride
        filt = decompressed[row_start]
        row  = decompressed[row_start+1 : row_start+1+w*channels]
        for x in range(w):
            idx = (y * w + x) * 4
            if has_alpha:
                r, g, b, a = row[x*4], row[x*4+1], row[x*4+2], row[x*4+3]
            else:
                r, g, b = row[x*3], row[x*3+1], row[x*3+2]
                a = 255
            pixels[idx]   = r
            pixels[idx+1] = g
            pixels[idx+2] = b
            pixels[idx+3] = a
    return pixels, w, h


def _write_png_rgba(pixels: bytearray, w: int, h: int) -> bytes:
    raw_rows = bytearray()
    for y in range(h):
        raw_rows += b'\x00'
        for x in range(w):
            idx = (y * w + x) * 4
            raw_rows += pixels[idx:idx+4]
    compressed = zlib.compress(bytes(raw_rows), 9)
    png  = b'\x89PNG\r\n\x1a\n'
    png += _png_chunk(b'IHDR', struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    png += _png_chunk(b'IDAT', compressed)
    png += _png_chunk(b'IEND', b'')
    return bytes(png)


def _write_png_rgb(pixels: bytearray, w: int, h: int) -> bytes:
    """Write RGB PNG (no alpha) — for ICO compatibility."""
    raw_rows = bytearray()
    for y in range(h):
        raw_rows += b'\x00'
        for x in range(w):
            idx = (y * w + x) * 4
            raw_rows += pixels[idx:idx+3]
    compressed = zlib.compress(bytes(raw_rows), 9)
    png  = b'\x89PNG\r\n\x1a\n'
    png += _png_chunk(b'IHDR', struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += _png_chunk(b'IDAT', compressed)
    png += _png_chunk(b'IEND', b'')
    return bytes(png)


def composite_on_dark(logo_pixels: bytearray, lw: int, lh: int,
                      out_size: int,
                      bg: tuple = (10, 14, 20),
                      padding_frac: float = 0.10) -> bytearray:
    """
    Composite the logo (RGBA) centered on a dark background square.
    The logo is scaled to fit inside out_size × (1 - 2*padding_frac).
    """
    import math

    # Scale logo to fit
    logo_area  = int(out_size * (1 - 2 * padding_frac))
    scale      = logo_area / max(lw, lh)
    scaled_w   = int(lw * scale)
    scaled_h   = int(lh * scale)
    offset_x   = (out_size - scaled_w) // 2
    offset_y   = (out_size - scaled_h) // 2

    # Scale logo pixels with bilinear-ish nearest-neighbour
    scaled = bytearray(scaled_w * scaled_h * 4)
    for dy in range(scaled_h):
        sy = int(dy / scale)
        sy = min(sy, lh - 1)
        for dx in range(scaled_w):
            sx = int(dx / scale)
            sx = min(sx, lw - 1)
            src = (sy * lw + sx) * 4
            dst = (dy * scaled_w + dx) * 4
            scaled[dst:dst+4] = logo_pixels[src:src+4]

    # Create output canvas
    out = bytearray(out_size * out_size * 4)
    for i in range(out_size * out_size):
        out[i*4]   = bg[0]
        out[i*4+1] = bg[1]
        out[i*4+2] = bg[2]
        out[i*4+3] = 255

    # Alpha-composite logo onto canvas
    for dy in range(scaled_h):
        cy = offset_y + dy
        if cy < 0 or cy >= out_size:
            continue
        for dx in range(scaled_w):
            cx = offset_x + dx
            if cx < 0 or cx >= out_size:
                continue
            src = (dy * scaled_w + dx) * 4
            dst = (cy * out_size + cx) * 4
            sa  = scaled[src+3] / 255.0
            # Logo is mostly dark on white — invert for dark bg compositing
            # White pixels become transparent, dark pixels become white/accent
            r, g, b, a = scaled[src], scaled[src+1], scaled[src+2], scaled[src+3]

            # For white-bg logo: invert so dark logo elements become light on dark bg
            luma = 0.299 * r + 0.587 * g + 0.114 * b
            if a > 10:
                inv_alpha = 1.0 - (luma / 255.0)  # dark pixels → opaque, white → transparent
                if inv_alpha > 0.05:
                    # Tint with ice-blue accent (#00d4ff)
                    fr = int(0   * inv_alpha + bg[0] * (1 - inv_alpha))
                    fg = int(212 * inv_alpha + bg[1] * (1 - inv_alpha))
                    fb = int(255 * inv_alpha + bg[2] * (1 - inv_alpha))
                    out[dst]   = max(0, min(255, fr))
                    out[dst+1] = max(0, min(255, fg))
                    out[dst+2] = max(0, min(255, fb))
                    out[dst+3] = 255

    return out


def use_sips_for_icns(src_png: Path) -> bool:
    """True if we should use sips+iconutil (macOS native, best quality)."""
    return sys.platform == "darwin" and shutil.which("sips") and shutil.which("iconutil")


def main():
    print("Generating AEGLOS Analytics Pro icon from official logo…")
    print(f"  Source: {LOGO_SRC}")

    # ── Read source logo ──────────────────────────────────────────────────────
    logo_pixels, lw, lh = _read_png_rgba(LOGO_SRC)
    print(f"  Logo size: {lw}×{lh}")

    # ── Build 1024×1024 composited PNG ────────────────────────────────────────
    comp_1024 = composite_on_dark(logo_pixels, lw, lh, out_size=1024)
    png_1024  = BUILD_DIR / "icon_1024.png"
    png_1024.write_bytes(_write_png_rgba(comp_1024, 1024, 1024))
    print(f"  Written: {png_1024} ({png_1024.stat().st_size // 1024} KB)")

    # ── macOS .icns via sips + iconutil ───────────────────────────────────────
    if use_sips_for_icns(png_1024):
        iconset = BUILD_DIR / "icon.iconset"
        iconset.mkdir(exist_ok=True)

        spec = [
            ("icon_16x16.png",       16),
            ("icon_16x16@2x.png",    32),
            ("icon_32x32.png",       32),
            ("icon_32x32@2x.png",    64),
            ("icon_128x128.png",     128),
            ("icon_128x128@2x.png",  256),
            ("icon_256x256.png",     256),
            ("icon_256x256@2x.png",  512),
            ("icon_512x512.png",     512),
            ("icon_512x512@2x.png",  1024),
        ]
        for fname, s in spec:
            out_path = iconset / fname
            subprocess.run(
                ["sips", "-z", str(s), str(s), str(png_1024), "--out", str(out_path)],
                check=True, capture_output=True,
            )

        icns_path = BUILD_DIR / "icon.icns"
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(icns_path)],
            check=True
        )
        shutil.rmtree(iconset)
        print(f"  Written: {icns_path} ({icns_path.stat().st_size // 1024} KB)")
    else:
        # Fallback: write composite PNG as .icns placeholder (won't work on macOS but
        # allows the build script to continue on non-macOS)
        icns_placeholder = BUILD_DIR / "icon.icns"
        icns_placeholder.write_bytes(png_1024.read_bytes())
        print(f"  Warning: iconutil not available — placeholder icns written")

    # ── Windows .ico (16, 32, 48, 256) ────────────────────────────────────────
    sizes_ico = [16, 32, 48, 256]
    images = []
    for s in sizes_ico:
        comp = composite_on_dark(logo_pixels, lw, lh, out_size=s)
        images.append(_write_png_rgb(comp, s, s))

    ico_path = BUILD_DIR / "icon.ico"
    n = len(images)
    header  = struct.pack("<HHH", 0, 1, n)
    entries = b""
    data    = b""
    offset  = 6 + n * 16
    for s, img in zip(sizes_ico, images):
        w = s if s < 256 else 0
        entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(img), offset)
        offset  += len(img)
        data    += img
    ico_path.write_bytes(header + entries + data)
    print(f"  Written: {ico_path} ({ico_path.stat().st_size // 1024} KB)")

    print("Icon generation complete.")


if __name__ == "__main__":
    main()
