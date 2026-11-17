
import asyncio
import json
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urldefrag, urlparse

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

SOURCE = "https://www.rangdhonu.live/?m=1"

OUTPUT = "found-links.json"

TIMEOUT = 60000

requests_seen = set()
responses_seen = []
candidates = set()
streams = []
errors = []


def normalize(url, base=SOURCE):
    if not url:
        return None

    url = str(url).strip()
    url = url.replace("\\/", "/")
    url = url.replace("\\u0026", "&")

    if url.startswith(("http://", "https://", "/")):
        url = urljoin(base, url)
    else:
        return None

    url, _ = urldefrag(url)

    return url


def is_playlist(url):
    path = urlparse(url).path.lower()
    return path.endswith((".m3u", ".m3u8"))


def extract_urls(text, base):
    patterns = [
        r'https?://[^\s\'"<>\\]+',
        r'["\']([^"\']+\.m3u8?(?:\?[^"\']*)?)["\']',
        r'["\']([^"\']+\.php(?:\?[^"\']*)?)["\']'
    ]

    for pattern in patterns:
        for match in re.findall(pattern, text, re.I):
            url = normalize(match, base)

            if url:
                yield url


async def main():

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox"]
        )

        page = await browser.new_page(
            viewport={"width": 1365, "height": 900}
        )

        page.on(
            "request",
            lambda req: requests_seen.add(req.url)
        )

        page.on(
            "response",
            lambda res: responses_seen.append(res)
        )

        print("Opening Rangdhonu website...")

        try:
            response = await page.goto(
                SOURCE,
                wait_until="domcontentloaded",
                timeout=TIMEOUT
            )

            print("HTTP status:", response.status if response else "Unknown")

            await page.wait_for_timeout(12000)

            title = await page.title()
            html = await page.content()

            print("Page title:", title)

            if "google.com/sorry" in page.url:
                errors.append(
                    "Google anti-bot verification blocked GitHub browser."
                )

            elif "sorry" in title.lower():
                errors.append(
                    "Google verification page detected."
                )

            # Inspect rendered HTML
            for url in extract_urls(html, page.url):
                if is_playlist(url):
                    candidates.add(url)

            # Inspect links, scripts and iframe sources
            elements = await page.locator(
                "[src], [href], [data-src], [data-url], [data-file]"
            ).evaluate_all("""
                els => els.map(el => ({
                    src: el.getAttribute('src'),
                    href: el.getAttribute('href'),
                    dataSrc: el.getAttribute('data-src'),
                    dataUrl: el.getAttribute('data-url'),
                    dataFile: el.getAttribute('data-file')
                }))
            """)

            for element in elements:
                for value in element.values():
                    url = normalize(value, page.url)

                    if url and is_playlist(url):
                        candidates.add(url)

            # Inspect iframe pages
            for frame in page.frames:
                try:
                    frame_html = await frame.content()

                    for url in extract_urls(frame_html, frame.url):
                        if is_playlist(url):
                            candidates.add(url)

                except Exception:
                    pass

            # Inspect JavaScript resource URLs
            resources = await page.evaluate("""
                () => performance.getEntriesByType('resource')
                    .map(x => x.name)
            """)

            for resource in resources:
                url = normalize(resource, page.url)

                if url and is_playlist(url):
                    candidates.add(url)

        except Exception as e:
            errors.append("Browser error: " + str(e))

        # Inspect browser network responses
        print("Inspecting network responses...")

        for res in responses_seen:

            url = res.url

            if is_playlist(url):
                candidates.add(url)

            try:
                content_type = (
                    res.headers.get("content-type", "").lower()
                )

                if (
                    "mpegurl" in content_type
                    or "vnd.apple" in content_type
                ):
                    body = await res.body()

                    if body.lstrip().startswith(b"#EXTM3U"):
                        candidates.add(url)

            except Exception:
                pass

        await browser.close()

    # Verify candidates using playlist content
    print("Candidates found:", len(candidates))

    import requests

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0"
    })

    for url in sorted(candidates):

        print("Checking:", url)

        try:
            r = session.get(
                url,
                timeout=20,
                stream=True
            )

            if r.status_code not in (200, 206):
                continue

            data = next(r.iter_content(8192), b"")
            r.close()

            body = data.decode(
                "utf-8-sig",
                errors="ignore"
            ).strip()

            if body.startswith("#EXTM3U"):

                streams.append({
                    "url": url,
                    "type": (
                        "m3u8"
                        if urlparse(url).path.lower().endswith(".m3u8")
                        else "m3u"
                    ),
                    "status": "VALID"
                })

                print("VALID:", url)

        except Exception as e:
            errors.append(
                "Validation error: " + url + " | " + str(e)
            )

    report = {
        "source": SOURCE,
        "checked_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "total_streams": len(streams),
        "streams": streams,
        "total_requests": len(requests_seen),
        "total_candidates": len(candidates),
        "page_title": title if "title" in locals() else "",
        "page_url": page.url if "page" in locals() else SOURCE,
        "errors": errors
    }

    with open(
        OUTPUT,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            report,
            f,
            indent=2,
            ensure_ascii=False
        )

    print("\nDetection completed.")
    print("Valid playlists:", len(streams))

    print("Report saved:", OUTPUT)


if __name__ == "__main__":
    asyncio.run(main())
