
import re
import json
import requests
from urllib.parse import urljoin
from pathlib import Path
from datetime import datetime, timezone

BASE_URL = "https://nova-tv1.samimadnan5552.workers.dev/?match=match-10"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
}

PATTERN = re.compile(
    r'https?://[^\s"\'<>\\]+?\.(?:m3u8?|mpd)(?:\?[^\s"\'<>\\]*)?',
    re.I
)

session = requests.Session()
session.headers.update(HEADERS)

visited = set()
found = set()
errors = []

def scan(url):
    if url in visited or len(visited) >= 40:
        return

    visited.add(url)

    try:
        response = session.get(url, timeout=25)
        response.raise_for_status()
        content = response.text

        # Detect stream URLs
        for link in PATTERN.findall(content):
            found.add(link.rstrip("),;"))

        # Detect external JavaScript files
        scripts = re.findall(
            r'<script[^>]+src=["\']([^"\']+)',
            content, re.I
        )

        for script in scripts:
            scan(urljoin(url, script))

        # Detect possible API/config endpoints
        endpoints = re.findall(
            r'["\']([^"\']*(?:api|playlist|channel|match|stream)[^"\']*)["\']',
            content, re.I
        )

        for endpoint in endpoints:
            if endpoint.startswith(("http://", "https://", "/")):
                scan(urljoin(url, endpoint))

    except Exception as error:
        errors.append({
            "url": url,
            "error": str(error)
        })

scan(BASE_URL)

# Build JSON output
result = {
    "source": BASE_URL,
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "total_streams": len(found),
    "streams": [
        {
            "url": link,
            "type": (
                "HLS" if ".m3u8" in link.lower()
                else "M3U" if ".m3u" in link.lower()
                else "MPEG-DASH"
            )
        }
        for link in sorted(found)
    ],
    "scanned_urls": len(visited),
    "errors": errors
}

Path("found-links.json").write_text(
    json.dumps(result, indent=2, ensure_ascii=False),
    encoding="utf-8"
)

print(json.dumps(result, indent=2, ensure_ascii=False))
print("\nJSON saved: found-links.json")
