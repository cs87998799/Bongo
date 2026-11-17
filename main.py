
import json
import re
import requests
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

API_URL = "https://live.indiansserials.com/channels"

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

def is_direct_playlist(url):
    if not isinstance(url, str):
        return False

    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False

    return bool(re.search(r"\.(m3u8|m3u)(?:$|[?#])", url, re.I))

def main():
    print("Fetching Rangdhonu channel catalog...")

    response = requests.get(
        API_URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30
    )
    response.raise_for_status()

    data = response.json()
    channels = data.get("channels", [])

    if not isinstance(channels, list):
        raise ValueError("Invalid channels array")

    direct = []
    references = []

    for channel in channels:
        if not isinstance(channel, dict):
            continue

        name = channel.get("name", "Unknown")
        url = channel.get("url", "")

        item = {
            "id": channel.get("id", ""),
            "name": name,
            "category": channel.get("cat", ""),
            "type": channel.get("type", ""),
            "image": channel.get("img", ""),
            "url": url
        }

        if is_direct_playlist(url):
            direct.append(item)
        elif isinstance(url, str) and url.startswith(("w1:", "w2:")):
            references.append({
                "id": item["id"],
                "name": name,
                "reference": url,
                "type": item["type"]
            })

    # JSON output
    json_data = {
        "source": API_URL,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "total_channels": len(channels),
        "direct_playlists": len(direct),
        "worker_references": len(references),
        "channels": direct,
        "worker_references_list": references
    }

    (OUTPUT_DIR / "channels.json").write_text(
        json.dumps(json_data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # M3U output
    lines = ["#EXTM3U"]

    for channel in direct:
        name = channel["name"]
        category = channel["category"]
        logo = channel["image"]
        url = channel["url"]

        lines.append(
            f'#EXTINF:-1 tvg-logo="{logo}" group-title="{category}",{name}'
        )
        lines.append(url)

    (OUTPUT_DIR / "channels.m3u").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8"
    )

    # Report
    report = f"""RANGDHONU PLAYLIST DETECTION REPORT
Checked: {json_data["checked_at"]}

Total channels: {len(channels)}
Direct M3U/M3U8: {len(direct)}
Worker references: {len(references)}

Direct playlists:
"""

    for channel in direct:
        report += f'{channel["name"]} | {channel["url"]}\n'

    report += "\nWorker references:\n"

    for item in references:
        report += f'{item["name"]} | {item["reference"]}\n'

    (OUTPUT_DIR / "report.txt").write_text(
        report, encoding="utf-8"
    )

    print(report)
    print("Output files created successfully.")

if __name__ == "__main__":
    main()
