
import json
import re
import requests
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

SITE = "https://toffeelive.com/en"
BASE = "https://toffeelive.com"

OUT = Path("output")
OUT.mkdir(exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0"}

CATALOG = {
    "Bangla & Local News/Entertainment": [
        "NTV", "Channel i", "Somoy TV", "Bangla TV",
        "Ekhon TV", "Global TV", "Jamuna TV",
        "Rajdhani TV", "Independent TV", "Channel S"
    ],
    "Sports Channels": [
        "Sony Ten Sports 1 HD", "Sony Ten Sports 2 HD",
        "Sony Ten Sports 5 HD", "Eurosport HD",
        "EPL Channel 1", "SAFF Live 1", "SAFF Live 2",
        "SAFF Live 3", "SAFF Live 4"
    ],
    "Movie Channels": [
        "Toffee Movies", "Sony PIX HD", "Movie Bangla",
        "Zee Cinema HD", "Zee Bangla Cinema",
        "Sony MAX HD", "B4U Movies APAC",
        "Zee Cafe", "& Pictures HD"
    ],
    "Entertainment & Regional Channels": [
        "Zee Bangla", "Zee TV HD", "Zee Bollywood",
        "Zee Action", "Zee Anmol", "Zing",
        "Sony Entertainment Television HD"
    ],
    "News & International Channels": [
        "Al Jazeera", "Channel News Asia",
        "TRT World", "Saudi Sunnah"
    ]
}

# HUM was requested separately; it was not visible
# in the supplied screenshot.
EXTRA_TARGETS = ["HUM"]

session = requests.Session()
session.headers.update(HEADERS)

resources = set()
inspected = []
errors = []
public_playlists = set()

def add_resource(url):
    url = urljoin(BASE, url.strip())

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        return

    if parsed.netloc not in (
        "toffeelive.com",
        "www.toffeelive.com"
    ):
        return

    if re.search(r"\.(js|json)(?:\?|$)", parsed.path, re.I):
        resources.add(url)

def is_media_url(url):
    return bool(
        re.search(r"\.(m3u8|m3u)(?:$|[?#])", url, re.I)
    )

def is_vod_or_trailer(url):
    text = url.lower()

    blocked = [
        "trailer", "vod", "movie", "episode",
        "season", "film", "preview"
    ]

    return any(word in text for word in blocked)

def inspect_content(content):
    # Find public JS/JSON references
    patterns = [
        r'https?://[^"\'\s<>]+',
        r'["\']([^"\']+\.(?:js|json)(?:\?[^"\']*)?)["\']'
    ]

    for pattern in patterns:
        for match in re.findall(pattern, content, re.I):
            add_resource(match)

    # Find public playlist URLs
    urls = re.findall(
        r'https?://[^"\'\s<>]+?\.(?:m3u8|m3u)(?:\?[^"\'\s<>]*)?',
        content,
        re.I
    )

    for url in urls:
        if not is_vod_or_trailer(url):
            public_playlists.add(url)

def main():
    print("Starting Toffee Channel Detector...")

    try:
        response = session.get(SITE, timeout=30)
        print("Website status:", response.status_code)
        response.raise_for_status()

        html = response.text
        inspect_content(html)

        # Inspect first-party script resources
        scripts = re.findall(
            r'<script[^>]+src=["\']([^"\']+)["\']',
            html,
            re.I
        )

        for script in scripts:
            add_resource(script)

    except requests.RequestException as error:
        errors.append(f"Website: {error}")

    # Inspect public JS and JSON files
    queue = list(resources)
    seen = set()

    while queue and len(seen) < 100:
        url = queue.pop(0)

        if url in seen:
            continue

        seen.add(url)

        try:
            response = session.get(url, timeout=20)

            inspected.append({
                "url": url,
                "status": response.status_code
            })

            if not response.ok:
                continue

            before = set(resources)
            inspect_content(response.text)

            new_resources = resources - before
            queue.extend(
                item for item in new_resources
                if item not in seen
            )

        except requests.RequestException as error:
            errors.append(f"{url}: {error}")

    timestamp = datetime.now(timezone.utc).isoformat()

    channels = []

    for category, names in CATALOG.items():
        for name in names:
            channels.append({
                "name": name,
                "category": category,
                "metadata_source": "User supplied screenshot",
                "stream_url": None,
                "stream_status": "NOT FOUND"
            })

    for name in EXTRA_TARGETS:
        channels.append({
            "name": name,
            "category": "Additional requested target",
            "metadata_source": "User request",
            "stream_url": None,
            "stream_status": "NOT FOUND"
        })

    result = {
        "source": SITE,
        "checked_at": timestamp,
        "total_catalog_channels": len(channels),
        "public_playlist_count": len(public_playlists),
        "channels": channels,
        "unmapped_public_playlists": sorted(public_playlists),
        "inspected_resources": inspected,
        "errors": errors
    }

    (OUT / "channels.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # Do not assign an unrelated playlist to a channel.
    lines = ["#EXTM3U"]

    (OUT / "channels.m3u").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8"
    )

    report = [
        "TOFFEE CHANNEL DETECTION REPORT",
        f"Checked: {timestamp}",
        f"Catalog channels: {len(channels)}",
        f"Public playlists: {len(public_playlists)}",
        "",
        "CHANNEL STATUS:"
    ]

    for channel in channels:
        report.append(
            f'{channel["name"]} | {channel["category"]} | '
            f'{channel["stream_status"]}'
        )

    report.extend(["", "UNMAPPED PUBLIC PLAYLISTS:"])
    report.extend(
        sorted(public_playlists)
        or ["No public playlist found."]
    )

    report.extend(["", "INSPECTED RESOURCES:"])

    for item in inspected:
        report.append(
            f'{item["status"]} | {item["url"]}'
        )

    report.extend(["", "ERRORS:"])
    report.extend(errors or ["None"])

    (OUT / "report.txt").write_text(
        "\n".join(report),
        encoding="utf-8"
    )

    print("\n".join(report))
    print("\nDetection completed.")

if __name__ == "__main__":
    main()
