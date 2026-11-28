#!/usr/bin/env python3
"""Convert the Bongo Live TV app's Firebase channels node into M3U."""
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from pathlib import Path

DATABASE = "https://bongo-live-tv-49434-default-rtdb.firebaseio.com/channels.json"

def main():
    req = Request(DATABASE, headers={"User-Agent": "Mozilla/5.0 Bongo-M3U-Exporter"})
    try:
        with urlopen(req, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise SystemExit(f"Could not read Firebase channels node: {exc}")

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Firebase did not return JSON: {exc}")

    if not isinstance(data, dict) or not data:
        raise SystemExit(
            "Firebase channels node is empty or not publicly readable. "
            "No playlist written; check Firebase database rules/authentication."
        )

    lines = ["#EXTM3U"]
    seen = set()
    for key, channel in data.items():
        if not isinstance(channel, dict):
            continue
        name = str(channel.get("name") or key).strip()
        url = str(channel.get("intent") or "").strip()
        logo = str(channel.get("image") or "").strip()
        if not url.startswith(("http://", "https://", "rtmp://", "rtsp://")):
            continue
        if url in seen:
            continue
        seen.add(url)
        # Escape quote characters in attributes to keep M3U metadata valid.
        logo = logo.replace('"', "%22")
        safe_name = name.replace("\r", " ").replace("\n", " ").replace(",", " ")
        lines.append(f'#EXTINF:-1 tvg-name="{safe_name}" tvg-logo="{logo}",{safe_name}')
        lines.append(url)

    if not seen:
        raise SystemExit("Firebase returned channel records, but no usable direct stream URLs were found.")

    Path("bongo_live_tv.m3u").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Created bongo_live_tv.m3u with {len(seen)} unique streams.")

if __name__ == "__main__":
    main()
