
import asyncio
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from playwright.async_api import async_playwright

SOURCE = "https://www.rangdhonu.live/?m=1"
OUTPUT = "found-links.json"

network = []
candidates = set()
errors = []


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox"]
        )

        page = await browser.new_page()

        async def capture(response):
            try:
                request = response.request
                headers = await response.all_headers()

                item = {
                    "url": response.url,
                    "status": response.status,
                    "type": request.resource_type,
                    "content_type": headers.get("content-type", "")
                }

                network.append(item)

                url = response.url.lower()
                ct = item["content_type"].lower()

                if (
                    any(x in url for x in [
                        ".m3u", ".m3u8", ".mpd",
                        "playlist", "manifest", "stream"
                    ])
                    or any(x in ct for x in [
                        "mpegurl", "dash+xml", "video/"
                    ])
                ):
                    candidates.add(response.url)

                if request.resource_type in ["xhr", "fetch"]:
                    try:
                        if int(headers.get("content-length", "0") or 0) > 2000000:
                            return

                        body = await response.text()

                        if len(body) <= 2000000:
                            if (
                                "#EXTM3U" in body
                                or re.search(
                                    r'https?://[^\s"\'<>]+',
                                    body
                                )
                            ):
                                item["body_sample"] = body[:15000]

                                for match in re.findall(
                                    r'https?://[^\s"\'<>]+',
                                    body
                                ):
                                    if any(x in match.lower() for x in [
                                        ".m3u", ".m3u8", ".mpd"
                                    ]):
                                        candidates.add(match)

                    except Exception:
                        pass

            except Exception as e:
                errors.append(str(e))

        page.on(
            "response",
            lambda response: asyncio.create_task(
                capture(response)
            )
        )

        try:
            print("Opening Rangdhonu...")
            await page.goto(
                SOURCE,
                wait_until="domcontentloaded",
                timeout=60000
            )

            await page.wait_for_timeout(8000)

            print("Page:", page.url)

            # Capture available channel names and clickable elements
            elements = await page.locator(
                "a, button, [onclick], [role=button]"
            ).evaluate_all("""
                els => els.map(el => ({
                    tag: el.tagName,
                    text: (el.innerText || el.getAttribute('aria-label') || '').trim(),
                    href: el.getAttribute('href'),
                    onclick: el.getAttribute('onclick')
                })).filter(x => x.text)
            """)

            print("Clickable elements:", len(elements))

            # Click BTV News channel
            locator = page.get_by_text(
                "BTV News",
                exact=True
            )

            if await locator.count():
                await locator.first.click(timeout=15000)
                print("BTV News clicked.")
            else:
                errors.append("BTV News channel not found.")

            # Wait for player and media requests
            await page.wait_for_timeout(20000)

            print("Player URL:", page.url)

            # Inspect frames
            for frame in page.frames:
                try:
                    html = await frame.content()

                    for match in re.findall(
                        r'https?://[^\s"\'<>]+',
                        html
                    ):
                        if any(x in match.lower() for x in [
                            ".m3u", ".m3u8", ".mpd"
                        ]):
                            candidates.add(match)

                except Exception:
                    pass

        except Exception as e:
            errors.append("Browser: " + str(e))

        await browser.close()

    report = {
        "source": SOURCE,
        "checked_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "total_requests": len(network),
        "total_candidates": len(candidates),
        "candidates": sorted(candidates),
        "network": network,
        "clickable_elements": elements if "elements" in locals() else [],
        "errors": errors
    }

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(
            report,
            f,
            indent=2,
            ensure_ascii=False
        )

    print("Requests:", len(network))
    print("Candidates:", len(candidates))
    print("Report:", OUTPUT)


if __name__ == "__main__":
    asyncio.run(main())
