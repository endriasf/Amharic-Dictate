"""Draw the Amharic Dictate logo (a mesob — woven basket — seen from above: stitched rings that
spread out like sound, with a voice wave in the centre) and every file made from it.
Needs rsvg-convert and Pillow; outputs are committed, so builds don't need this script."""
import math, os, subprocess, tempfile
from PIL import Image

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A = os.path.join(here, "assets")
ART = os.path.join(here, "build", "art")
G1, G2, DARK, GOLD, CREAM = "#2FA36A", "#16603F", "#0F3D2A", "#E2B14A", "#F4EBD0"
STATE = {"ready": (G1, G2), "active": ("#E25B4F", "#A8322A"), "busy": ("#8A9690", "#5F6B65"),
         "paused": ("#E9A93A", "#B37718")}


def mark(rings=(36, 56, 76), stitch=(5.5, 15), gap=12, core=22, center=G2, fade=0.2):
    out = []
    w, h = stitch
    for i, r in enumerate(rings):
        n = int(2 * math.pi * r / gap)
        for k in range(n):
            a = 2 * math.pi * k / n
            col = (GOLD if (k // 3 + i) % 2 else CREAM) if i % 2 else (CREAM if (k + i) % 4 else GOLD)
            x, y = 100 + r * math.cos(a), 100 + r * math.sin(a)
            out.append(f'<rect x="{x-w/2:.2f}" y="{y-h/2:.2f}" width="{w}" height="{h}" rx="{w/2}" fill="{col}" '
                       f'transform="rotate({math.degrees(a)+125:.1f} {x:.2f} {y:.2f})" opacity="{1-i*fade:.2f}"/>')
    out.append(f'<circle cx="100" cy="100" r="{core}" fill="{CREAM}"/>')
    s = core / 22
    for dx, bh in ((-12, 10), (-6, 20), (0, 26), (6, 16), (12, 8)):
        out.append(f'<rect x="{100+dx*s-2*s:.2f}" y="{100-bh*s/2:.2f}" width="{4*s:.2f}" height="{bh*s:.2f}" '
                   f'rx="{2*s:.2f}" fill="{center}"/>')
    return "".join(out)


def small_mark(center=G2):                    # 16–32 px: one ring of big stitches
    return mark(rings=(68,), stitch=(15, 36), gap=29, core=38, center=center, fade=0)


def mid_mark(center=G2):                      # 48–64 px: two rings
    return mark(rings=(48, 74), stitch=(9, 22), gap=19, core=28, center=center, fade=0.15)


def svg(body, size=200, defs=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 200 200">'
            f'<defs>{defs}</defs>{body}</svg>')


def tile(body, c1=G1, c2=G2, shape="square"):
    defs = (f'<linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{c1}"/>'
            f'<stop offset="1" stop-color="{c2}"/></linearGradient>')
    bg = ('<rect width="200" height="200" rx="46" fill="url(#g)"/>' if shape == "square"
          else '<circle cx="100" cy="100" r="100" fill="url(#g)"/>')
    return svg(bg + body, defs=defs)


def png(svg_text, px, path):
    with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False) as f:
        f.write(svg_text)
    subprocess.run(["rsvg-convert", "-w", str(px), "-h", str(px), f.name, "-o", path], check=True)
    os.unlink(f.name)


def main():
    os.makedirs(ART, exist_ok=True)
    big_tile, mid_tile, small_tile = tile(mark()), tile(mid_mark()), tile(small_mark())
    open(os.path.join(A, "logo.svg"), "w").write(svg(mark()))
    open(os.path.join(A, "logo_tile.svg"), "w").write(big_tile)
    tmp = tempfile.mkdtemp()
    frames = []
    for px in (16, 24, 32, 48, 64, 128, 256):          # Windows icon: small sizes use the simpler mark
        p = os.path.join(tmp, f"{px}.png")
        png(small_tile if px <= 32 else mid_tile if px <= 64 else big_tile, px, p)
        frames.append(Image.open(p).convert("RGBA"))
    frames[-1].save(os.path.join(A, "icon.ico"), sizes=[f.size for f in frames], append_images=frames[:-1])
    png(big_tile, 256, os.path.join(A, "logo_256.png"))
    for state, (c1, c2) in STATE.items():               # tray icon per state (round, simple mark)
        png(tile(small_mark(center=c2), c1, c2, "circle"), 64, os.path.join(A, f"tray_{state}.png"))
    for pct, px in ((100, 58), (150, 87), (200, 116)):  # installer corner icon
        png(mid_tile if px < 100 else big_tile, px, os.path.join(ART, f"icon-{pct}.png"))
    print("logo files written")


if __name__ == "__main__":
    main()
