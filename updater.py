"""
Update check (can be turned off in Settings).

Once a day the app asks GitHub for the version number of the newest release. Nothing about the
user, their voice or their text is sent: it's a plain request for public release information,
the same as opening the releases page in a browser. Nothing is downloaded or installed
automatically; the person decides whether to open the download page.
"""
import json
import re
import urllib.request

REPO = "endriasf/Amharic-Dictate"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES = f"https://github.com/{REPO}/releases"
CHECK_EVERY_S = 24 * 3600


def parse_version(text: str):
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    return tuple(int(x or 0) for x in m.groups()) if m else None


def latest_release(current: str, timeout: float = 8.0):
    """(version, page_url) if a newer release exists, else None. Raises on network errors."""
    req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"AmharicDictate/{current}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:            # https only, normal certificate checks
        data = json.loads(r.read(200_000).decode("utf-8"))
    if data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name", ""))
    new, cur = parse_version(tag), parse_version(current)
    if not new or not cur or new <= cur:
        return None
    url = str(data.get("html_url", ""))
    if not url.startswith(RELEASES + "/"):                              # only ever open this project's own page
        url = RELEASES
    return ".".join(map(str, new)), url
