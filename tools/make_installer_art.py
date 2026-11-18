"""Draw the installer background (build/art/background-*.png): the dark green theme with a large,
faint mesob ring from the logo. Needs rsvg-convert; outputs are committed."""
import os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_logo import mark, name_text, DARK

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = os.path.join(here, "build", "art")
os.makedirs(out, exist_ok=True)

for pct, s in ((100, 1.0), (150, 1.5), (200, 2.0)):
    w, h = int(600 * s), int(440 * s)
    ring = 520                                   # ring size at 100%, mostly off the right edge
    body = (f'<rect width="600" height="440" fill="{DARK}"/>'
            f'<g opacity=".16" transform="translate({40 - ring / 2} {420 - ring / 2}) scale({ring / 200})">{mark()}</g>')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 600 440">{body}</svg>'
    with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False) as f:
        f.write(svg)
    subprocess.run(["rsvg-convert", "-w", str(w), "-h", str(h), f.name, "-o",
                    os.path.join(out, f"background-{pct}.png")], check=True)
    os.unlink(f.name)
print("installer art written")

# Welcome / Finished pages: the logo and AmharicDictate name in the left column (transparent background)
for pct, s in ((100, 1.0), (150, 1.5), (200, 2.0)):
    w, h = int(164 * s), int(314 * s)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 164 314">'
           f'<g transform="translate(17 26) scale(.65)">{mark()}</g>{name_text(82, 190, 17.5, True, "middle")}</svg>')
    with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False) as f:
        f.write(svg)
    subprocess.run(["rsvg-convert", "-w", str(w), "-h", str(h), f.name, "-o",
                    os.path.join(out, f"welcome-{pct}.png")], check=True)
    os.unlink(f.name)
print("welcome art written")
