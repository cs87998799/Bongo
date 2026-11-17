
import re
import json
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, urldefrag, unquote

import requests
from bs4 import BeautifulSoup

SOURCE = "https://www.rangdhonu.live/?m=1"
OUTPUT = "found-links.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
    "Accept": "*/*"
}

MAX_PAGES = 35
TIMEOUT = 20

session = requests.Session()
session.headers.update(HEADERS)

scanned = set()
candidates = set()
errors = []
streams = []


def normalize(url, base=None):
    if not url:
        return None

    url = unquote(str(url).strip())
    url = url.replace("\\/", "/").replace("\\u0026", "&")

    if base:
        url = urljoin(base, url)

    url, _ = urldefrag(url)

    if not url.startswith(("http://", "https://")):
        return None

    return url


def is_internal(url):
    return urlparse(url).netloc.lower() == urlparse(SOURCE).netloc.lower()


def extract_urls(text, base):
    patterns = [
        r'https?://[^\s\'"<>\\]+',
        r'(?:src|href|file|url|playlist|source|manifest)\s*[:=]\s*[\'"]([^\'"]+)[\'"]',
        r'[\'"]([^\'"]+\.(?:m3u8?|php|json)(?:\?[^\'"]*)?)[\'"]',
        r'(?<![\w/])(/[^\s\'"<>]+)'
    ]

    for pattern in patterns:
        for match in re.findall(pattern, text, re.I):
            if isinstance(match, tuple):
                match = match[0]

            url = normalize(match, base)

            if url:
                yield url


def inspect_content(url, content, base):
    text = content.decode("utf-8", errors="ignore")

    for item in extract_urls(text, base):
        parsed = urlparse(item)
        path = parsed.path.lower()

        if re.search(r'\.m3u8?$', path):
            candidates.add(item)

    return text


def scan_page(url):
    if url in scanned or len(scanned) >= MAX_PAGES:
        return

    scanned.add(url)

    print("Scanning:", url)

    try:
        response = session.get(
            url,
            timeout=TIMEOUT
        )

        response.raise_for_status()

        content = response.content
        text = content.decode("utf-8", errors="ignore")

        inspect_content(url, content, url)

        content_type = response.headers.get(
            "Content-Type", ""
        ).lower()

        if "html" not in content_type and "<html" not in text[:1000].lower():
            return

        soup = BeautifulSoup(text, "html.parser")

        for tag in soup.find_all(True):
            for attr in [
                "href", "src", "data-src",
                "data-url", "data-file",
                "data-hls", "data-playlist",
                "content"
            ]:
                value = tag.get(attr)

                if value:
                    found = normalize(value, response.url)

                    if found:
                        path = urlparse(found).path.lower()

                        if re.search(r'\.m3u8?$', path):
                            candidates.add(found)

                        elif is_internal(found) and tag.name in [
                            "a", "iframe", "script"
                        ]:
                            if found not in scanned:
                                if len(scanned) < MAX_PAGES:
                                    scan_page(found)

        for script in soup.find_all("script"):
            script_url = script.get("src")

            if script_url:
                js_url = normalize(script_url, response.url)

                if js_url:
                    if is_internal(js_url):
                        scan_page(js_url)
                    else:
                        try:
                            r = session.get(
                                js_url,
                                timeout=TIMEOUT
                            )
                            if r.ok:
                                inspect_content(
                                    js_url, r.content, js_url
                                )
                        except Exception as e:
                            errors.append(
                                f"JS {js_url}: {str(e)}"
                            )
            else:
                inspect_content(
                    response.url,
                    script.get_text().encode("utf-8"),
                    response.url
                )

    except Exception as e:
        errors.append(f"{url}: {str(e)}")


def validate_playlist(url):
    try:
        response = session.get(
            url,
            headers={"Range": "bytes=0-8191"},
            timeout=TIMEOUT,
            stream=True,
            allow_redirects=True
        )

        if response.status_code not in (200, 206):
            response.close()
            return None

        data = next(response.iter_content(8192), b"")
        content_type = response.headers.get(
            "Content-Type", ""
        ).lower()

        response.close()

        body = data.decode("utf-8-sig", errors="ignore").strip()

        if "#EXTM3U" not in body[:2048]:
            return None

        return {
            "url": response.url,
            "type": (
                "m3u8"
                if ".m3u8" in urlparse(response.url).path.lower()
                else "m3u"
            )
        }

    except Exception as e:
        errors.append(f"Validation {url}: {str(e)}")
        return None


def main():
    print("Starting Rangdhonu M3U detector...")

    scan_page(SOURCE)

    print("\nFound candidates:", len(candidates))

    for url in sorted(candidates):
        print("Checking:", url)

        result = validate_playlist(url)

        if result and result not in streams:
            streams.append(result)
            print("VALID:", result["url"])

        time.sleep(0.2)

    report = {
        "source": SOURCE,
        "checked_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "total_streams": len(streams),
        "streams": streams,
        "scanned_urls": sorted(scanned),
        "errors": errors
    }

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(
            report,
            f,
            indent=2,
            ensure_ascii=False
        )

    print("\nDetection completed.")
    print("Valid playlists:", len(streams))
    print("Output:", OUTPUT)


if __name__ == "__main__":
    main()
