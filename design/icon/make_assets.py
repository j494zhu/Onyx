"""Render the full static/icons asset set from a preset in icon_svg.py.

Usage:
  python design/icon/make_assets.py A6
  python design/icon/make_assets.py A6 --stroke 8 --large-stroke 4.5 --trim 0.95

Writes: favicon.svg, favicon-16/32.png, favicon.ico (16/32/48),
apple-touch-icon.png (180), icon-192.png, icon-512.png. Needs Pillow.
"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import icon_svg as S  # noqa: E402

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("Pillow is required: pip install pillow")

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "static", "icons")


def _hex(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def _bezier(p0, p1, p2, p3, t):
    mt = 1 - t
    return (mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0],
            mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1])


def _wave_points(trim, n=900):
    segs = [S.SEG1, S.trim_seg2(trim)]
    pts = []
    for seg in segs:
        pts += [_bezier(*seg, i / n) for i in range(n + 1)]
    return pts


def _shadow_polys(p):
    """(fill_hex, [poly pts in 64-space]) list for the preset's shadow + grid."""
    polys = []
    kind, boundary = p.get("shadow_kind", "none"), p.get("shadow", 0.0)
    dx, dy = math.cos(math.radians(S.ANG)), -math.sin(math.radians(S.ANG))

    def quad(xl, xr, fill):
        polys.append((fill, [(xl + S.T * dx, 32 + S.T * dy), (xr + S.T * dx, 32 + S.T * dy),
                             (xr - S.T * dx, 32 - S.T * dy), (xl - S.T * dx, 32 - S.T * dy)]))

    if kind == "single" and boundary > 0:
        quad(-30.0, boundary, "#f4f2ef")
    elif kind == "echo" and boundary > 0:
        total = sum(S.ECHO_W)
        ws, x0 = S.ECHO_W, boundary - total
        if x0 < 0:
            ws, x0 = [w * boundary / total for w in S.ECHO_W], 0.0
        quad(-30.0, x0, S.SOLID_SHADE)
        x, si = x0, 0
        for i, w in enumerate(ws):
            if i % 2 == 1:
                quad(x, x + w, S.ECHO_SHADES[si])
                si += 1
            x += w
    return polys


def render(p, size, stroke, rounded, ss=6):
    Ssz = size * ss
    k = Ssz / 64.0
    img = Image.new("RGBA", (Ssz, Ssz), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    tile = _hex(p.get("tile", "#ffffff")) + (255,)
    border = _hex(p.get("border", "#e4e7ea")) + (255,)

    mask = Image.new("L", (Ssz, Ssz), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, Ssz - 1, Ssz - 1], radius=14 * k, fill=255)

    d.rectangle([0, 0, Ssz, Ssz], fill=tile)
    if p.get("grid"):
        gcol = _hex("#dbe5d2") + (255,)
        a = math.radians(-8)
        ca, sa = math.cos(a), math.sin(a)
        def rot(x, y):
            return ((x - 32) * ca - (y - 32) * sa + 32) * k, ((x - 32) * sa + (y - 32) * ca + 32) * k
        for v in range(-30, 95, 10):
            d.line([rot(v, -30), rot(v, 94)], fill=gcol, width=max(1, round(0.8 * k)))
            d.line([rot(-30, v), rot(94, v)], fill=gcol, width=max(1, round(0.8 * k)))
    for fill, pts in _shadow_polys(p):
        d.polygon([(x * k, y * k) for x, y in pts], fill=_hex(fill) + (255,))

    bw = max(1, round(1.5 * k))
    d.rounded_rectangle([bw // 2, bw // 2, Ssz - 1 - bw // 2, Ssz - 1 - bw // 2],
                        radius=13.25 * k, outline=border, width=bw)

    trim = p.get("trim", 1.0)
    pts = _wave_points(trim)
    xs = [q[0] for q in pts]
    xmin, xmax = min(xs), max(xs)
    c0, c1 = _hex(p["start"]), _hex(p["end"])

    if p.get("use_halo"):
        layer = Image.new("RGBA", (Ssz, Ssz), (0, 0, 0, 0))
        dl = ImageDraw.Draw(layer)
        hr = (stroke + 2.5) / 2 * k
        for x, y in pts:
            f = (x - xmin) / (xmax - xmin)
            alpha = 255 if f < 0.45 else (0 if f > 0.65 else round(255 * (0.65 - f) / 0.2))
            if alpha:
                dl.ellipse([x * k - hr, y * k - hr, x * k + hr, y * k + hr],
                           fill=(255, 255, 255, alpha))
        img = Image.alpha_composite(img, layer)
        d = ImageDraw.Draw(img)

    r = stroke / 2 * k
    for x, y in pts:
        f = min(1.0, max(0.0, (x - xmin) / (xmax - xmin)))
        col = tuple(round(a + (b - a) * f) for a, b in zip(c0, c1)) + (255,)
        d.ellipse([x * k - r, y * k - r, x * k + r, y * k + r], fill=col)

    _, tip = S.wave_path(trim)
    dr = (stroke / 2 + 0.5) * k
    d.ellipse([tip[0] * k - dr, tip[1] * k - dr, tip[0] * k + dr, tip[1] * k + dr],
              fill=_hex(p["end"]) + (255,))

    if rounded:
        img.putalpha(mask)
    return img.resize((size, size), Image.LANCZOS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("preset", choices=sorted(S.PRESETS))
    ap.add_argument("--stroke", type=float, default=8.0, help="favicon stroke width")
    ap.add_argument("--large-stroke", type=float, default=4.5, help="large-icon stroke width")
    ap.add_argument("--trim", type=float, default=None,
                    help="right-curve length t (0..1]; default: preset value or 1.0")
    ap.add_argument("--start", help="override gradient start color")
    ap.add_argument("--end", help="override gradient end color")
    ap.add_argument("--shadow", type=float, help="override shadow right edge (0 = off)")
    args = ap.parse_args()

    p = dict(S.PRESETS[args.preset])
    if args.trim is not None:
        p["trim"] = args.trim
    p.setdefault("trim", 1.0)
    for key in ("start", "end", "shadow"):
        v = getattr(args, key)
        if v is not None:
            p[key] = v

    os.makedirs(OUT, exist_ok=True)
    svg = S.build_svg(**{k: v for k, v in p.items()}, stroke=args.stroke)
    with open(os.path.join(OUT, "favicon.svg"), "w", encoding="utf-8") as f:
        f.write(svg)

    for sz in (16, 32):
        render(p, sz, args.stroke, rounded=True).save(os.path.join(OUT, f"favicon-{sz}.png"))
    ico = [render(p, sz2, args.large_stroke if sz2 >= 48 else args.stroke, rounded=True)
           for sz2 in (48, 32, 16)]
    ico[0].save(os.path.join(OUT, "favicon.ico"), format="ICO",
                sizes=[(48, 48), (32, 32), (16, 16)], append_images=ico[1:])
    for sz, name in ((180, "apple-touch-icon.png"), (192, "icon-192.png"), (512, "icon-512.png")):
        render(p, sz, args.large_stroke, rounded=False).convert("RGB").save(os.path.join(OUT, name))

    for f in sorted(os.listdir(OUT)):
        print(f, os.path.getsize(os.path.join(OUT, f)), "bytes")


if __name__ == "__main__":
    main()
