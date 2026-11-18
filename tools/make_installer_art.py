"""Draw the installer's background and corner icon (build/art/*.png). Run once after design changes;
the PNGs are committed so the Windows build doesn't need this script's font."""
import math, os, random
from PIL import Image, ImageDraw, ImageFont

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = os.path.join(here, "build", "art")
os.makedirs(out, exist_ok=True)
FONT = "/usr/share/fonts/truetype/freefont/FreeSerif.ttf"      # has Ge'ez letters
BG, LETTER, WAVE, BAR = (15, 61, 42), (36, 98, 70), (52, 128, 92), (70, 160, 112)
LETTERS = "ሀለሐመሠረሰሸቀበተቸኀነኘአከኸወዐዘዠየደጀገጠጨጰጸፀፈፐ"


def background(w, h, s):
    """w x h at scale s (1 = 100% DPI). Art kept to the edges and bottom so text stays clear."""
    im = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(im)
    rnd = random.Random(7)
    font = ImageFont.truetype(FONT, int(40 * s))
    small = ImageFont.truetype(FONT, int(26 * s))
    for i in range(18):                                   # letters along the top edge and the bottom band
        x = int((i % 9) * w / 9 + rnd.uniform(0, w / 18))
        y = int(rnd.uniform(4, 30) * s) if i < 9 else int(h - rnd.uniform(48, 80) * s)
        d.text((x, y), rnd.choice(LETTERS), font=font if i % 3 else small, fill=LETTER)
    base = h - 120 * s                                     # sound waves across the lower part
    for k, amp in ((0, 16), (1, 10)):
        pts = [(x, base + 8 * s * k + amp * s * math.sin(x / (34 * s) + k) * (0.55 + 0.45 * math.sin(x / (90 * s))))
               for x in range(0, w + 1, max(1, int(2 * s)))]
        d.line(pts, fill=WAVE, width=max(1, int((2 - k * 0.5) * s)))
    bx = w - 70 * s                                        # small level bars, bottom right
    for j, hh in enumerate((14, 28, 20, 34, 12)):
        x = bx + j * 10 * s
        d.line([(x, base - 46 * s - hh * s / 2), (x, base - 46 * s + hh * s / 2)], fill=BAR, width=int(4 * s))
    return im


for pct, s in ((100, 1.0), (150, 1.5), (200, 2.0)):
    background(int(600 * s), int(440 * s), s).save(os.path.join(out, f"background-{pct}.png"), optimize=True)
icon = Image.open(os.path.join(here, "assets", "icon.ico"))
icon.size = (256, 256)
icon = icon.convert("RGBA")
for pct, px in ((100, 58), (150, 87), (200, 116)):
    icon.resize((px, px), Image.LANCZOS).save(os.path.join(out, f"icon-{pct}.png"), optimize=True)
print("ok", sorted(os.listdir(out)))
