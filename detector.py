import re
import json
import requests
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

BASE_URL = "https://nova-tv1.samimadnan5552.workers.dev/?match=match-10"

OUTPUT = Path("found-links.json")
MAX_PAGES = 40

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/130 Safari/537.36"
    )
}

STREAM_PATTERN = re.compile(
    r'https?://[^\s"\'<>\\]+?\.(?:m3u8?|mpd)(?:\?[^\s"\'<>\\]*)?'
    r'|(?:/|\.?/)[A-Za-z0-9._~%/-]+\.(?:m3u8?|mpd)(?:\?[^\s"\'<>\\]*)?',
    re.I
)

SCRIPT_PATTERN = re.compile(
    r'<script[^>]+src=["\']([^"\']+)["\']',
    re.I
)

API_PATTERN = re.compile(
    r'["\']([^"\']*(?:api|playlist|channel|match|stream)[^"\']*)["\']',
    re.I
)

session = requests.Session()
session.headers.update(HEADERS)

visited = set()
found = {}
errors = []
queue = [BASE_URL]

def get_stream_type(url):
    path = urlparse(url).path.lower()

    if path.endswith(".m3u8"):
        return "HLS"
    if path.endswith(".m3u"):
        return "M3U"
    if path.endswith(".mpd"):
        return "MPEG-DASH"

    return "UNKNOWN"

def scan(url):
    try:
        print("Scanning:", url)

        response = session.get(url, timeout=25)
        response.raise_for_status()

        content = response.text.replace("\\/", "/")

        # Detect stream URLs
        for match in STREAM_PATTERN.findall(content):
            link = urljoin(response.url, match.rstrip("),;"))

            if get_stream_type(link) != "UNKNOWN":
                found[link] = {
                    "url": link,
                    "type": get_stream_type(link),
                    "source_page": url
                }

        # Detect JavaScript files
        for script in SCRIPT_PATTERN.findall(content):
            target = urljoin(response.url, script)

            if urlparse(target).netloc == urlparse(BASE_URL).netloc:
                if target not in visited and target not in queue:
                    queue.append(target)

        # Detect possible API/config endpoints
        for endpoint in API_PATTERN.findall(content):
            target = urljoin(response.url, endpoint)

            if urlparse(target).netloc == urlparse(BASE_URL).netloc:
                if target not in visited and target not in queue:
                    queue.append(target)

    except Exception as error:
        print("Scan error:", str(error))

        errors.append({
            "url": url,
            "error": str(error)
        })

while queue and len(visited) < MAX_PAGES:
    current = queue.pop(0)

    if current in visited:
        continue

    visited.add(current)
    scan(current)

result = {
    "source": BASE_URL,
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "total_streams": len(found),
    "streams": list(found.values()),
    "scanned_urls": len(visited),
    "errors": errors
}

OUTPUT.write_text(
    json.dumps(result, indent=2, ensure_ascii=False),
    encoding="utf-8"
)

print("\n========== RESULT ==========")
print("Total streams:", len(found))
print("Scanned URLs:", len(visited))
print("Errors:", len(errors))
print("JSON saved:", OUTPUT)

if found:
    for item in found.values():
        print(item["type"], item["url"])
else:
    print("No direct stream links detected.")
