import re, json
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin
from playwright.sync_api import sync_playwright

URL = "https://nexflixtv.lovable.app/"
EXT = re.compile(r"\.(m3u8?|mpd)(\?|#|$)", re.I)
BODY_URL = re.compile(r"https?://[^\s\"'<>\\)]+?\.(?:m3u8?|mpd)[^\s\"'<>\\)]*", re.I)

found = {}          # url -> where it was found
all_requests = []   # debug log


def add(url, src):
    url = url.replace("\\/", "/").replace("\\u0026", "&")
    if url not in found:
        found[url] = src


def scan_text(text, src):
    text = text.replace("\\/", "/").replace("\\u0026", "&")
    for u in BODY_URL.findall(text):
        add(u, src)


def on_request(r):
    all_requests.append(f"{r.method} {r.resource_type} {r.url}")
    if EXT.search(r.url):
        add(r.url, "request")


def on_response(r):
    try:
        if EXT.search(r.url):
            add(r.url, "response-url")
        ct = (r.headers.get("content-type") or "").lower()
        if any(k in ct for k in ("json", "javascript", "text", "mpegurl", "xml")):
            body = r.text()
            if len(body) > 8_000_000:
                return
            if body.lstrip().startswith("#EXTM3U"):
                add(r.url, "playlist-body")
            scan_text(body, "body:" + r.url[:80])
    except Exception:
        pass


with sync_playwright() as p:
    browser = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
    ctx = browser.new_context(
        viewport={"width": 1366, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    )
    page = ctx.new_page()
    page.on("request", on_request)
    page.on("response", on_response)

    page.goto(URL, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(6000)

    # scroll to trigger lazy loading
    for _ in range(5):
        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(1000)

    # collect internal links
    hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
    host = urlparse(URL).netloc
    internal = sorted({h.split("#")[0] for h in hrefs if urlparse(h).netloc == host})[:20]

    # click cards / buttons on the home page
    for sel in ["video", "button", "[role=button]", "img", "[class*=card]", "[class*=channel]"]:
        try:
            els = page.query_selector_all(sel)[:8]
            for el in els:
                try:
                    el.click(timeout=1500)
                    page.wait_for_timeout(1500)
                    page.go_back(wait_until="load", timeout=5000) if page.url != URL and page.url.split("#")[0] not in internal else None
                except Exception:
                    pass
        except Exception:
            pass

    # visit each internal page
    for link in internal:
        try:
            page.goto(link, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(4000)
            for frame in page.frames:
                try:
                    scan_text(frame.content(), "frame:" + frame.url[:80])
                except Exception:
                    pass
        except Exception:
            pass

    scan_text(page.content(), "rendered-html")
    page.screenshot(path="debug_page.png", full_page=True)
    open("debug_page.html", "w", encoding="utf-8").write(page.content())
    browser.close()

open("debug_requests.txt", "w", encoding="utf-8").write("\n".join(all_requests))

channels = []
for i, (u, src) in enumerate(sorted(found.items()), 1):
    name = urlparse(u).path.rstrip("/").split("/")[-1] or f"Channel {i}"
    channels.append({"id": i, "name": name, "url": u, "found_in": src})

with open("Sarah.json", "w", encoding="utf-8") as f:
    json.dump({"source": URL,
               "generated": datetime.now(timezone.utc).isoformat(),
               "count": len(channels),
               "channels": channels}, f, indent=2, ensure_ascii=False)

with open("Sarah.m3u", "w", encoding="utf-8") as f:
    f.write("#EXTM3U\n")
    for c in channels:
        f.write(f'#EXTINF:-1 tvg-id="{c["id"]}" tvg-name="{c["name"]}",{c["name"]}\n{c["url"]}\n')

print(f"Found {len(channels)} link(s)")
for c in channels:
    print(c["url"], "<-", c["found_in"])
print(f"Total requests logged: {len(all_requests)}")
