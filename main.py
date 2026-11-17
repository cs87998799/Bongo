
import json
import re
import requests
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

SITE_URL = "https://toffeelive.com/en"
OUTPUT = Path("output")
OUTPUT.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PublicLinkChecker/1.0)"
}

found = set()
checked = []

def add_url(url):
    if not isinstance(url, str):
        return

    url = url.strip()
    if not url:
        return

    if re.search(r"\.(m3u8|m3u)(?:$|[?#])", url, re.I):
        found.add(url)

def main():
    print("Checking Toffee public website...")

    try:
        response = requests.get(
            SITE_URL,
            headers=HEADERS,
            timeout=30
        )
        print("Website status:", response.status_code)
        response.raise_for_status()

        html = response.text

        # Find playlist references in public HTML
        patterns = [
            r'https?://[^"\'\s<>]+?\.m3u8(?:\?[^"\'\s<>]*)?',
            r'https?://[^"\'\s<>]+?\.m3u(?:\?[^"\'\s<>]*)?',
        ]

        for pattern in patterns:
            for match in re.findall(pattern, html, re.I):
                add_url(match)

        # Find public JSON/API references
        json_urls = set(
            urljoin(SITE_URL, match)
            for match in re.findall(
                r'''["']([^"']+\.json(?:\?[^"']*)?)["']''',
                html,
                re.I
            )
        )

        for json_url in json_urls:
            try:
                r = requests.get(
                    json_url,
                    headers=HEADERS,
                    timeout=15
                )

                checked.append({
                    "url": json_url,
                    "status": r.status_code
                })

                if r.ok:
                    text = r.text
                    for match in re.findall(
                        r'https?://[^"\'\s<>]+',
                        text
                    ):
                        add_url(match)

            except requests.RequestException:
                continue

    except requests.RequestException as error:
        print("Website request failed:", error)

    timestamp = datetime.now(timezone.utc).isoformat()

    playlists = sorted(found)

    result = {
        "source": SITE_URL,
        "checked_at": timestamp,
        "total_playlists": len(playlists),
        "playlists": playlists,
        "checked_json_sources": checked
    }

    (OUTPUT / "channels.json").write_text(
        json.dumps(result, indent=2),
        encoding="utf-8"
    )

    m3u = ["#EXTM3U"]

    for index, url in enumerate(playlists, 1):
        m3u.extend([
            f"#EXTINF:-1,Toffee Public Link {index}",
            url
        ])

    (OUTPUT / "channels.m3u").write_text(
        "\n".join(m3u) + "\n",
        encoding="utf-8"
    )

    report = [
        "TOFFEE PUBLIC LINK DETECTOR",
        f"Checked: {timestamp}",
        f"Total detected playlists: {len(playlists)}",
        "",
        "Detected links:"
    ]

    report.extend(playlists or ["No public M3U/M3U8 links detected."])

    (OUTPUT / "report.txt").write_text(
        "\n".join(report),
        encoding="utf-8"
    )

    print("\n".join(report))

if __name__ == "__main__":
    main()
