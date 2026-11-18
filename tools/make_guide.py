"""Build guide.html (the offline user guide opened from the app) from the user part of README.md.
Run after editing README.md:  python tools/make_guide.py
Needs: pip install markdown fonttools, and the Poppins font (OFL) — it's embedded so the page
looks the same offline on every PC."""
import base64, html, io, os, re, sys

import markdown
from fontTools import subset
from fontTools.ttLib import TTFont

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
sys.path.insert(0, os.path.join(here, "tools"))
from config import APP_VERSION          # noqa: E402
from make_logo import mark              # noqa: E402

POPPINS = os.environ.get("POPPINS_DIR", "/usr/share/fonts/truetype/google-fonts")


def font_b64(name):
    """Poppins, cut down to basic Latin, as an embedded font."""
    f = TTFont(os.path.join(POPPINS, name))
    opts = subset.Options(); opts.layout_features = ["kern", "liga"]
    s = subset.Subsetter(opts); s.populate(unicodes=range(0x20, 0x7F)); s.subset(f)
    b = io.BytesIO(); f.save(b)
    return base64.b64encode(b.getvalue()).decode()


readme = open(os.path.join(here, "README.md"), encoding="utf-8").read()
user = readme[: readme.index("## Licence and credits")]              # stop before developer-facing parts
user = re.sub(r'<p align="center">.*?</p>\s*', "", user, flags=re.S)  # README banner (the page has its own header)
user = re.sub(r"^<img [^>]*>\s*", "", user, flags=re.M)
user = re.sub(r"\n## 1\. Install.*?(?=\n## 2\.)", "\n", user, flags=re.S)  # already installed
user = re.sub(r"^(#{2,3}) \d+[a-e]?\. ", r"\1 ", user, flags=re.M)          # no section numbers
user = re.sub(r"^# Amharic Dictate\s*\n", "", user, count=1, flags=re.M)    # title is in the header
body = markdown.markdown(user, extensions=["tables", "sane_lists", "toc"])
toc = "".join(f'<li><a href="#{m.group(1)}">{html.escape(re.sub("<.*?>", "", m.group(2)))}</a></li>'
              for m in re.finditer(r'<h2 id="([^"]+)">(.*?)</h2>', body))
logo = f'<svg class="mark" viewBox="0 0 200 200" aria-hidden="true">{mark()}</svg>'
ring = f'<svg class="ring" viewBox="0 0 200 200" aria-hidden="true">{mark()}</svg>'
medium, light = font_b64("Poppins-Medium.ttf"), font_b64("Poppins-Light.ttf")

page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; font-src data:">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Amharic Dictate — how to use</title>
<style>
@font-face{{font-family:Brand;font-weight:500;src:url(data:font/ttf;base64,{medium}) format("truetype")}}
@font-face{{font-family:Brand;font-weight:300;src:url(data:font/ttf;base64,{light}) format("truetype")}}
:root{{--green:#1E7A4E;--green-hi:#2FA36A;--deep:#0F3D2A;--gold:#C9952E;--bg:#FFFFFF;--panel:#F4F6F5;
  --text:#1D2320;--muted:#56605B;--line:#DDE3E0}}
@media (prefers-color-scheme:dark){{:root{{--green:#5CC08A;--green-hi:#7EE0A8;--bg:#1E2220;--panel:#262B29;
  --text:#EEF2F0;--muted:#A9B3AE;--line:#3A413E;--gold:#E2B14A}}}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:"Segoe UI","Ebrima","Nyala",sans-serif;line-height:1.6;color:var(--text);background:var(--bg)}}
.hero{{position:relative;overflow:hidden;background:var(--deep);color:#fff;padding:34px 0 30px}}
.hero .ring{{position:absolute;right:-90px;top:-70px;width:330px;height:330px;opacity:.13}}
.wrap{{max-width:880px;margin:0 auto;padding:0 28px}}
.brand{{position:relative;display:flex;align-items:center;gap:20px}}
.mark{{width:92px;height:92px;flex:none}}
.name{{font-family:Brand,"Segoe UI",sans-serif;font-size:40px;line-height:1.1;letter-spacing:-.5px}}
.name b{{font-weight:500}} .name span{{font-weight:300;color:#5CC08A}}
.sub{{margin-top:6px;color:#CFE8DB;font-size:15px}}
.pill{{display:inline-block;margin-top:10px;font-size:12px;color:#0F3D2A;background:#9BE7BE;border-radius:20px;padding:2px 10px}}
main.wrap{{padding-top:30px;padding-bottom:50px}}
nav{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 22px;margin:0 0 30px}}
nav b{{font-family:Brand,"Segoe UI",sans-serif;font-weight:500}}
nav ul{{columns:2;margin:.4em 0 0;padding-left:1.1em}} nav li{{margin:2px 0}}
h2{{font-family:Brand,"Segoe UI","Ebrima",sans-serif;font-weight:500;font-size:1.55em;margin:2.2em 0 .6em;
   padding-left:14px;border-left:5px solid var(--green)}}
h3{{font-family:Brand,"Segoe UI","Ebrima",sans-serif;font-weight:500;font-size:1.15em;margin:1.6em 0 .4em;color:var(--green)}}
a{{color:var(--green)}} strong{{color:inherit}}
code,kbd{{background:var(--panel);border:1px solid var(--line);border-radius:5px;padding:0 6px;font-size:.92em}}
table{{border-collapse:collapse;margin:1em 0;width:100%}} td,th{{border:1px solid var(--line);padding:7px 12px;text-align:left}}
th{{background:var(--deep);color:#fff;font-weight:600}} tr:nth-child(even) td{{background:var(--panel)}}
hr{{border:0;border-top:1px solid var(--line);margin:2em 0}}
blockquote{{margin:1em 0;padding:8px 16px;border-left:4px solid var(--gold);background:var(--panel);border-radius:0 8px 8px 0}}
footer{{border-top:1px solid var(--line);color:var(--muted);font-size:13px;padding:18px 0 30px}}
footer .row{{display:flex;align-items:center;gap:10px}} footer svg{{width:26px;height:26px}}
@media (max-width:620px){{nav ul{{columns:1}} .name{{font-size:30px}} .mark{{width:68px;height:68px}}}}
</style></head><body>
<header class="hero">{ring}<div class="wrap"><div class="brand">{logo}<div>
  <div class="name"><b>Amharic</b><span>Dictate</span></div>
  <div class="sub">How to use · Version {APP_VERSION}</div>
  <div class="pill">AI model: Amharic Speech-to-Text EFA v1 · works fully offline</div>
</div></div></div></header>
<main class="wrap">
<nav><b>Contents</b><ul>{toc}</ul></nav>
{body}
</main>
<footer><div class="wrap row"><svg viewBox="0 0 200 200" aria-hidden="true">{mark()}</svg>
<span>Amharic Dictate {APP_VERSION} · Created by Endrias F. Abitte · Everything you dictate stays on this computer.</span>
</div></footer>
</body></html>
"""
out = os.path.join(here, "assets", "guide.html")
open(out, "w", encoding="utf-8", newline="\n").write(page)
print("wrote", out, len(page), "bytes")
