
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

CATALOG_URL = "https://live.indiansserials.com/channels"
OUTPUT_JSON = "rangdhonu_report.json"
OUTPUT_M3U = "rangdhonu.m3u"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PublicCatalogScanner/1.0)",
    "Accept": "application/json, text/plain, */*",
    "Cache-Control": "no-cache",
}


def make_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def is_direct_playlist(value):
    if not isinstance(value, str):
        return False

    value = value.strip()

    if not value.startswith(("http://", "https://")):
        return False

    try:
        path = urlparse(value).path.lower()
    except Exception:
        return False

    return path.endswith((".m3u", ".m3u8"))


def clean_name(value):
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def find_playlists(data):
    found = []
    seen = set()

    name_keys = (
        "name", "title", "channel", "channelName",
        "channel_name", "displayName", "label"
    )

    url_keys = (
        "url", "stream", "streamUrl", "stream_url",
        "playlist", "playlistUrl", "playlist_url",
        "m3u", "m3u8", "src", "source"
    )

    def walk(item, parent_name=""):
        if isinstance(item, dict):
            current_name = parent_name

            for key in name_keys:
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    current_name = clean_name(value)
                    break

            # Check likely URL fields first.
            for key in url_keys:
                value = item.get(key)
                if is_direct_playlist(value):
                    url = value.strip()
                    if url not in seen:
                        seen.add(url)
                        found.append({
                            "name": current_name or f"Channel {len(found) + 1}",
                            "url": url,
                        })

            # Also inspect nested objects and arrays.
            for value in item.values():
                if isinstance(value, (dict, list)):
                    walk(value, current_name)

                elif is_direct_playlist(value):
                    url = value.strip()
                    if url not in seen:
                        seen.add(url)
                        found.append({
                            "name": current_name or f"Channel {len(found) + 1}",
                            "url": url,
                        })

        elif isinstance(item, list):
            for value in item:
                walk(value, parent_name)

    walk(data)
    return found


def write_m3u(playlists):
    lines = ["#EXTM3U"]

    for item in playlists:
        name = item["name"].replace(",", " ").strip()
        url = item["url"]

        lines.append(f"#EXTINF:-1,{name}")
        lines.append(url)

    with open(OUTPUT_M3U, "w", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")


def main():
    checked_at = datetime.now(timezone.utc).isoformat()
    report = {
        "source": CATALOG_URL,
        "checked_at": checked_at,
        "status": "unknown",
        "http_status": None,
        "content_type": None,
        "total_candidates": 0,
        "playlists": [],
        "message": "",
    }

    print("===================================")
    print(" RANGDHONU PUBLIC CATALOG SCANNER")
    print("===================================")
    print("Source:", CATALOG_URL)

    try:
        session = make_session()
        response = session.get(
            CATALOG_URL,
            headers=HEADERS,
            timeout=30,
        )

        report["http_status"] = response.status_code
        report["content_type"] = response.headers.get("Content-Type", "")

        print("HTTP Status:", response.status_code)
        print("Content-Type:", report["content_type"])

        response.raise_for_status()

        try:
            data = response.json()
        except ValueError:
            report["status"] = "error"
            report["message"] = (
                "API did not return valid JSON. "
                "It may have returned HTML or another response."
            )
            raise RuntimeError(report["message"])

        playlists = find_playlists(data)

        report["status"] = "success"
        report["total_candidates"] = len(playlists)
        report["playlists"] = playlists

        if playlists:
            report["message"] = "Direct public playlist URLs found."
        else:
            report["message"] = (
                "Catalog JSON was received, but no direct .m3u or .m3u8 "
                "URLs were exposed."
            )

        print("Direct playlist URLs:", len(playlists))

        for item in playlists:
            print("-", item["name"], "=>", item["url"])

        write_m3u(playlists)

    except Exception as error:
        if report["status"] == "unknown":
            report["status"] = "error"

        report["message"] = str(error)
        print("ERROR:", error)

        # Keep a valid empty M3U file for this scan.
        write_m3u([])

    finally:
        with open(OUTPUT_JSON, "w", encoding="utf-8") as file:
            json.dump(report, file, indent=2, ensure_ascii=False)

        print("-----------------------------------")
        print("JSON report:", OUTPUT_JSON)
        print("M3U file:", OUTPUT_M3U)
        print("Status:", report["status"])
        print("Total:", report["total_candidates"])
        print("===================================")

    if report["status"] == "error":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
