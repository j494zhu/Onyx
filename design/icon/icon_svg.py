"""Onyx "Pulse" icon — SVG builders and kept presets (A1 / A6 / A7 / GRID).

Single source of truth for the icon geometry. See README.md for the math.
Run directly to write preview_<name>.svg files next to this script.
"""
import math
import os

T = 60          # half-length of shadow boundary lines
ANG = 75        # shadow line angle, degrees from horizontal
ECHO_W = [1.53, 2.21, 1.275, 1.445, 1.02, 0.935, 0.765, 0.68]  # dense echo widths
ECHO_SHADES = ["#f3f1ee", "#f6f4f1", "#faf8f6", "#fcfbfa"]
SOLID_SHADE = "#f1efec"

# wave: M 9 36 C 17 16, 25 16, 32 34 C 38 50, 46 50, 55 24
SEG1 = ((9, 36), (17, 16), (25, 16), (32, 34))
SEG2 = ((32, 34), (38, 50), (46, 50), (55, 24))


def _lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def trim_seg2(t):
    """De Casteljau sub-curve [0, t] of SEG2. Returns (P0, C1, C2, End)."""
    p0, p1, p2, p3 = SEG2
    q1, q2, q3 = _lerp(p0, p1, t), _lerp(p1, p2, t), _lerp(p2, p3, t)
    r1, r2 = _lerp(q1, q2, t), _lerp(q2, q3, t)
    return p0, q1, r1, _lerp(r1, r2, t)


def wave_path(trim=1.0):
    (a, b, c, d) = SEG1
    p0, c1, c2, end = trim_seg2(trim)
    return (f"M {a[0]} {a[1]} C {b[0]} {b[1]}, {c[0]} {c[1]}, {d[0]} {d[1]} "
            f"C {c1[0]:.2f} {c1[1]:.2f}, {c2[0]:.2f} {c2[1]:.2f}, "
            f"{end[0]:.2f} {end[1]:.2f}"), end


def band(xl, xr, fill):
    dx, dy = math.cos(math.radians(ANG)), -math.sin(math.radians(ANG))
    pts = [(xl + T * dx, 32 + T * dy), (xr + T * dx, 32 + T * dy),
           (xr - T * dx, 32 - T * dy), (xl - T * dx, 32 - T * dy)]
    p = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
    return f"<polygon points='{p}' fill='{fill}' clip-path='url(#tile)'/>"


def echo_bands(boundary):
    """Solid shadow + alternating shrinking bands, right edge at `boundary`.
    boundary <= 0 disables the shadow entirely."""
    if boundary <= 0:
        return ""
    total = sum(ECHO_W)
    ws, x0 = ECHO_W, boundary - total
    if x0 < 0:                       # squeeze structure into small boundary
        ws, x0 = [w * boundary / total for w in ECHO_W], 0.0
    out, x, si = [band(-30.0, x0, SOLID_SHADE)], x0, 0
    for i, w in enumerate(ws):
        if i % 2 == 1:
            out.append(band(x, x + w, ECHO_SHADES[si]))
            si += 1
        x += w
    return "".join(out)


def single_band(boundary, shade="#f4f2ef"):
    return band(-30.0, boundary, shade) if boundary > 0 else ""


def grid_lines(color="#dbe5d2", step=10, width=0.8, angle=-8):
    lines = "".join(
        f"<line x1='{v}' y1='-30' x2='{v}' y2='94'/><line x1='-30' y1='{v}' x2='94' y2='{v}'/>"
        for v in range(-30, 95, step))
    return (f"<g transform='rotate({angle} 32 32)' stroke='{color}' "
            f"stroke-width='{width}' clip-path='url(#tile)'>{lines}</g>")


def halo(path_d, stroke):
    return ("<linearGradient id='og' x1='0' y1='0' x2='1' y2='0'>"
            "<stop offset='0' stop-color='#ffffff'/>"
            "<stop offset='0.45' stop-color='#ffffff'/>"
            "<stop offset='0.65' stop-color='#ffffff' stop-opacity='0'/></linearGradient>"
            f"<path d='{path_d}' fill='none' stroke='url(#og)' "
            f"stroke-width='{stroke + 2.5}' stroke-linecap='round'/>")


def build_svg(start, end, stroke=8, shadow=0.0, shadow_kind="none",
              use_halo=False, grid=False, trim=1.0, tile="#ffffff",
              border="#e4e7ea", dot_r=None):
    """shadow_kind: 'none' | 'single' | 'echo'; shadow = right edge x (0 = off)."""
    d, tip = wave_path(trim)
    dot_r = dot_r if dot_r is not None else stroke / 2
    bg = grid_lines() if grid else ""
    if shadow_kind == "single":
        bg += single_band(shadow)
    elif shadow_kind == "echo":
        bg += echo_bands(shadow)
    return f"""<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>
<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='0'>
<stop offset='0' stop-color='{start}'/><stop offset='1' stop-color='{end}'/></linearGradient>
<clipPath id='tile'><rect width='64' height='64' rx='14'/></clipPath></defs>
<rect width='64' height='64' rx='14' fill='{tile}'/>
{bg}
<rect x='0.75' y='0.75' width='62.5' height='62.5' rx='13.25' fill='none' stroke='{border}' stroke-width='1.5'/>
{halo(d, stroke) if use_halo else ""}
<path d='{d}' fill='none' stroke='url(#g)' stroke-width='{stroke}' stroke-linecap='round'/>
<circle cx='{tip[0]:.2f}' cy='{tip[1]:.2f}' r='{dot_r}' fill='{end}'/>
</svg>"""


PRESETS = {
    "A1": dict(start="#ffcf3f", end="#ff4d3d", shadow_kind="none"),
    "A6": dict(start="#FFE100", end="#ff4d3d", shadow_kind="echo",
               shadow=64.0 / 3, use_halo=True),
    "A7": dict(start="#FFE100", end="#ff4d3d", shadow_kind="echo",
               shadow=26.0, use_halo=True),
    "GRID": dict(start="#6bb388", end="#b7c95f", shadow_kind="none",
                 grid=True, tile="#f8faf3", border="#dfe8d5"),
    # 2026-07-18 定稿：青柠→翡翠，A6 光影，右曲线 0.94。
    # 线宽分档：<48px 用 9.5，>=48px 用 4.5（make_assets --stroke 9.5 --large-stroke 4.5）
    "FINAL": dict(start="#b7c95f", end="#6bb488", shadow_kind="echo",
                  shadow=64.0 / 3, use_halo=True, trim=0.94),
}


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    for name, p in PRESETS.items():
        path = os.path.join(here, f"preview_{name}.svg")
        with open(path, "w", encoding="utf-8") as f:
            f.write(build_svg(**p))
        print("wrote", path)
