
import asyncio
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin

from playwright.async_api import async_playwright

SOURCE = "https://www.rangdhonu.live/?m=1"
OUTPUT = "found-links.json"

CHANNEL_NAME = "BTV News"

network = []
candidates = set()
streams = []
errors = []
responses = []


def normalize_url(url):
    if not url:
        return None

    url = str(url).strip().replace("\\/", "/")

    if url.startswith(("http://", "https://")):
        return url

    return None


def extract_urls(text):
    if not text:
        return []

    patterns = [
        r'https?://[^\s"\'<>\\]+',
        r'["\']([^"\']+\.m3u8?(?:\?[^"\']*)?)["\']',
        r'["\']([^"\']+\.mpd(?:\?[^"\']*)?)["\']'
    ]

    found = set()

    for pattern in patterns:
        for match in re.findall(pattern, text, re.I):
            url = normalize_url(match)

            if url:
                found.add(url)

    return found


async def click_continue(page):
    print("Checking Telegram popup...")

    await page.wait_for_timeout(3000)

    selectors = [
        page.get_by_role(
            "button",
            name=re.compile("Continue to Watch", re.I)
        ),
        page.get_by_text(
            "Continue to Watch",
            exact=True
        )
    ]

    for locator in selectors:
        try:
            if await locator.count():
                if await locator.first.is_visible():
                    await locator.first.click(timeout=10000)
                    print("Continue to Watch clicked!")
                    await page.wait_for_timeout(20000)
                    return True
        except Exception:
            continue

    print("Continue button not found.")
    return False


async def process_responses():

    print("\nProcessing captured responses...")

    for response in responses:

        try:
            url = response.url
            status = response.status
            request_type = response.request.resource_type

            headers = await response.all_headers()
            content_type = headers.get(
                "content-type", ""
            ).lower()

            item = {
                "url": url,
                "status": status,
                "resource_type": request_type,
                "content_type": content_type
            }

            network.append(item)

            if status not in (200, 206):
                continue

            interesting = (
                any(x in url.lower() for x in [
                    ".m3u", ".mpd",
                    "playlist", "manifest",
                    "stream", "master"
                ])
                or any(x in content_type for x in [
                    "mpegurl",
                    "dash+xml",
                    "video/"
                ])
                or request_type in ["xhr", "fetch"]
            )

            if not interesting:
                continue

            try:
                body = await response.body()

                if len(body) > 2_000_000:
                    continue

                text = body.decode(
                    "utf-8-sig",
                    errors="ignore"
                )

                # Detect actual M3U content
                if text.lstrip().startswith("#EXTM3U"):
                    candidates.add(url)

                    streams.append({
                        "url": url,
                        "type": (
                            "m3u8"
                            if ".m3u8" in url.lower()
                            else "m3u"
                        ),
                        "status": "VALID",
                        "detected_from": "response_body"
                    })

                # Search JSON/API responses
                for found_url in extract_urls(text):

                    if any(x in found_url.lower() for x in [
                        ".m3u",
                        ".m3u8",
                        ".mpd"
                    ]):
                        candidates.add(found_url)

            except Exception:
                pass

        except Exception as e:
            errors.append(
                "Response processing: " + str(e)
            )


async def main():

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox"]
        )

        context = await browser.new_context(
            viewport={
                "width": 1365,
                "height": 900
            },
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            )
        )

        page = await context.new_page()

        # Capture network responses
        page.on(
            "response",
            lambda response: responses.append(response)
        )

        try:

            print("Opening Rangdhonu website...")

            response = await page.goto(
                SOURCE,
                wait_until="domcontentloaded",
                timeout=60000
            )

            print(
                "HTTP Status:",
                response.status if response else "Unknown"
            )

            await page.wait_for_timeout(8000)

            print("Page title:", await page.title())

            if "google.com/sorry" in page.url:
                errors.append(
                    "Google verification blocked the browser."
                )
                raise Exception("Google verification detected.")

            # Click selected channel
            print("\nSelecting channel:", CHANNEL_NAME)

            channel = page.get_by_text(
                CHANNEL_NAME,
                exact=True
            )

            if await channel.count() == 0:
                errors.append(
                    "Channel not found: " + CHANNEL_NAME
                )
            else:
                await channel.first.click(timeout=15000)

                print("Channel clicked.")

                await page.wait_for_timeout(4000)

                # Telegram popup handling
                await click_continue(page)

                print("Current player URL:", page.url)

                # Additional player loading time
                await page.wait_for_timeout(15000)

                # Inspect iframe URLs
                for frame in page.frames:
                    try:
                        frame_url = frame.url

                        if frame_url:
                            network.append({
                                "url": frame_url,
                                "resource_type": "iframe"
                            })

                        html = await frame.content()

                        for found in extract_urls(html):
                            if any(x in found.lower() for x in [
                                ".m3u",
                                ".m3u8",
                                ".mpd"
                            ]):
                                candidates.add(found)

                    except Exception:
                        pass

                # Inspect performance resources
                resources = await page.evaluate("""
                    () => performance.getEntriesByType('resource')
                        .map(item => item.name)
                """)

                for resource in resources:
                    if any(x in resource.lower() for x in [
                        ".m3u",
                        ".m3u8",
                        ".mpd",
                        "manifest",
                        "playlist"
                    ]):
                        candidates.add(resource)

        except Exception as e:
            errors.append("Browser error: " + str(e))

        # Process all captured responses
        await process_responses()

        await browser.close()

    # Remove duplicate streams
    unique_streams = {}

    for stream in streams:
        unique_streams[stream["url"]] = stream

    streams[:] = list(unique_streams.values())

    report = {
        "source": SOURCE,
        "channel_tested": CHANNEL_NAME,
        "checked_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "total_requests": len(network),
        "total_candidates": len(candidates),
        "total_streams": len(streams),
        "streams": streams,
        "candidates": sorted(candidates),
        "network": network,
        "errors": errors
    }

    with open(
        OUTPUT,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            report,
            file,
            indent=2,
            ensure_ascii=False
        )

    print("\n========== RESULTS ==========")
    print("Requests:", len(network))
    print("Candidates:", len(candidates))
    print("Valid streams:", len(streams))
    print("Report:", OUTPUT)


if __name__ == "__main__":
    asyncio.run(main())
