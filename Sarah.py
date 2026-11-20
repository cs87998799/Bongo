import re, json
from datetime import datetime, timezone
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

URL = "https://nexflixtv.lovable.app/"
PATTERN = re.compile(r"\.m3u8?(\?|$)", re.I)
HTML_PATTERN = re.compile(r"https?://[^\s\"'<>\\]+\.m3u8?[^\s\"'<>\\]*", re.I)

found = set()


def add(url):
    if PATTERN.search(url):
        found.add(url)


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.on("request", lambda r: add(r.url))
    page.on("response", lambda r: add(r.url))

    # also scan JSON/API responses for m3u links
    def scan_response(r):
        try:
            ct = r.headers.get("content-type", "")
            if "json" in ct or "javascript" in ct or "text" in ct:
                for u in HTML_PATTERN.findall(r.text()):
                    found.add(u)
        except Exception:
            pass

    page.on("response", scan_response)

    page.goto(URL, wait_until="networkidle")
    page.wait_for_timeout(8000)
    for u in HTML_PATTERN.findall(page.content()):
        found.add(u)
    browser.close()

links = sorted(found)

channels = []
for i, u in enumerate(links, 1):
    name = urlparse(u).path.rstrip("/").split("/")[-1] or f"Channel {i}"
    channels.append({"id": i, "name": name, "url": u})

# Sarah.json
with open("Sarah.json", "w", encoding="utf-8") as f:
    json.dump(
        {
            "source": URL,
            "generated": datetime.now(timezone.utc).isoformat(),
            "count": len(channels),
            "channels": channels,
        },
        f,
        indent=2,
        ensure_ascii=False,
    )

# Sarah.m3u
with open("Sarah.m3u", "w", encoding="utf-8") as f:
    f.write("#EXTM3U\n")
    for c in channels:
        f.write(f'#EXTINF:-1 tvg-id="{c["id"]}" tvg-name="{c["name"]}",{c["name"]}\n')
        f.write(c["url"] + "\n")

print(f"Found {len(channels)} link(s)")
for c in channels:
    print(c["url"])
