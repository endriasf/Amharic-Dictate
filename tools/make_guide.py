"""Build guide.html (the offline user guide opened from the app) from the user part of README.md.
Run after editing README.md:  python tools/make_guide.py   (needs: pip install markdown)"""
import html, os, re, sys

import markdown

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
readme = open(os.path.join(here, "README.md"), encoding="utf-8").read()
user = readme[: readme.index("## Licence and credits")]          # stop before developer-facing parts
user = re.sub(r"\n## 1\. Install.*?(?=\n## 2\.)", "\n", user, flags=re.S)  # already installed
user = re.sub(r"^(#{2,3}) \d+[a-e]?\. ", r"\1 ", user, flags=re.M)          # no section numbers
user = user.replace("# Amharic Dictate", "# Amharic Dictate — how to use", 1)
body = markdown.markdown(user, extensions=["tables", "sane_lists", "toc"])
toc = "".join(f'<li><a href="#{m.group(1)}">{html.escape(re.sub("<.*?>", "", m.group(2)))}</a></li>'
              for m in re.finditer(r'<h2 id="([^"]+)">(.*?)</h2>', body))
page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>Amharic Dictate — how to use</title>
<style>
body{{font-family:"Segoe UI","Ebrima","Nyala",sans-serif;max-width:860px;margin:0 auto;padding:24px 28px 60px;
     line-height:1.55;color:#1d1d1f;background:#fff}}
h1{{font-size:1.9em;margin-bottom:.2em}} h2{{margin-top:2em;border-bottom:1px solid #ddd;padding-bottom:.2em}}
h3{{margin-top:1.5em}} code,kbd{{background:#f2f2f4;border-radius:4px;padding:1px 5px;font-size:.95em}}
table{{border-collapse:collapse;margin:1em 0}} td,th{{border:1px solid #ccc;padding:5px 10px;text-align:left}}
th{{background:#f5f5f7}} nav{{background:#f5f5f7;border-radius:8px;padding:10px 18px;margin:1em 0 2em}}
nav ul{{margin:.3em 0;padding-left:1.2em}} a{{color:#0b62c4}} hr{{border:0;border-top:1px solid #ddd}}
@media (prefers-color-scheme:dark){{body{{background:#1e1e1e;color:#e6e6e6}} nav,th,code,kbd{{background:#2c2c2e}}
  a{{color:#6cb4ff}} h2{{border-color:#444}} td,th{{border-color:#444}}}}
</style></head><body>
{body.split("</h1>", 1)[0]}</h1>
<nav><b>Contents</b><ul>{toc}</ul></nav>
{body.split("</h1>", 1)[1]}
</body></html>
"""
out = os.path.join(here, "assets", "guide.html")
open(out, "w", encoding="utf-8", newline="\n").write(page)
print("wrote", out, len(page), "bytes")
