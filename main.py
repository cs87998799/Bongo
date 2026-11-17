
import json
import re
import requests
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

SITE = "https://toffeelive.com/en"

TARGETS = ["HUM", "Somoy", "NTV"]

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

OUT = Path("output")
OUT.mkdir(exist_ok=True)

session = requests.Session()
session.headers.update(HEADERS)

resources = set()
matches = []
errors = []

def add_resource(url):
    url = urljoin(SITE, url.strip())

    if urlparse(url).scheme in ("http", "https"):
        resources.add(url)

def extract_urls(text):
    patterns = [
        r'https?://[^"\'\s<>]+',
        r'["\']([^"\']+\.(?:js|json)(?:\?[^"\']*)?)["\']'
    ]

    for pattern in patterns:
        for match in re.findall(pattern, text, re.I):
            add_resource(match)

def find_channel_names(text):
    for name in TARGETS:
        if re.search(re.escape(name), text, re.I):
            matches.append(name)

def main():
    print("Starting Toffee public source inspection...")

    try:
        response = session.get(SITE, timeout=30)
        response.raise_for_status()
        html = response.text

        find_channel_names(html)
        extract_urls(html)

    except requests.RequestException as error:
        errors.append(str(error))

    # Inspect publicly referenced JavaScript and JSON resources
    candidates = [
        url for url in resources
        if re.search(r'\.(js|json)(?:\?|$)', url, re.I)
    ]

    inspected = []
    playlist_urls = set()

    for url in candidates:
        try:
            response = session.get(url, timeout=15)
            inspected.append({
                "url": url,
                "status": response.status_code
            })

            if not response.ok:
                continue

            content = response.text
            find_channel_names(content)

            # Collect only public playlist references
            for match in re.findall(
                r'https?://[^"\'\s<>]+?\.m3u8?(?:\?[^"\'\s<>]*)?',
                content,
                re.I
            ):
                if "trailer" not in match.lower() and \
                   "vod" not in match.lower():
                    playlist_urls.add(match)

        except requests.RequestException as error:
            errors.append(f"{url}: {error}")

    # Target channel report
    channel_results = []

    for name in TARGETS:
        found = any(
            re.search(re.escape(name), item, re.I)
            for item in matches
        )

        channel_results.append({
            "channel": name,
            "public_metadata_found": found,
            "status": "METADATA FOUND" if found else "NOT FOUND",
            "stream_url": None
        })

    timestamp = datetime.now(timezone.utc).isoformat()

    result = {
        "source": SITE,
        "checked_at": timestamp,
        "channels": channel_results,
        "public_playlist_count": len(playlist_urls),
        "public_playlists": sorted(playlist_urls),
        "inspected_resources": inspected,
        "errors": errors
    }

    (OUT / "channels.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    m3u = ["#EXTM3U"]

    for url in sorted(playlist_urls):
        m3u.extend([
            "#EXTINF:-1,Public Toffee Playlist",
            url
        ])

    (OUT / "channels.m3u").write_text(
        "\n".join(m3u) + "\n",
        encoding="utf-8"
    )

    report = [
        "TOFFEE CHANNEL DETECTION REPORT",
        f"Checked: {timestamp}",
        "",
        "TARGET CHANNELS:"
    ]

    for item in channel_results:
        report.append(
            f'{item["channel"]}: {item["status"]}'
        )

    report.extend([
        "",
        f"Public playlists: {len(playlist_urls)}",
        "",
        "PLAYLIST URLS:"
    ])

    report.extend(sorted(playlist_urls) or ["No public playlist found."])

    report.extend(["", "INSPECTED RESOURCES:"])

    for item in inspected:
        report.append(f'{item["status"]} | {item["url"]}')

    report.extend(["", "ERRORS:"])
    report.extend(errors or ["None"])

    (OUT / "report.txt").write_text(
        "\n".join(report),
        encoding="utf-8"
    )

    print("\n".join(report))


if __name__ == "__main__":
    main()
