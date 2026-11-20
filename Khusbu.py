import json
import re
import ipaddress
from urllib.parse import urljoin, urlparse

import requests
from playwright.sync_api import sync_playwright

SITE = "https://nexflixtv.lovable.app/"
JSON_FILE = "Khusbu.json"
M3U_FILE = "Khusbu.m3u"

found = set()
resources = set()
errors = []

URL_RE = re.compile(r"""https?://[^\s"'<>\\]+""", re.I)
REL_RE = re.compile(
    r"""["']([^"']+\.(?:m3u8?|m3u)(?:\?[^"']*)?)["']""", re.I
)


def add_from_text(text, base_url=""):
    if not text:
        return

    for match in URL_RE.findall(text):
        url = match.rstrip("),];}")
        parsed = urlparse(url)
        if parsed.scheme in ("http", "https"):
            path = parsed.path.lower()
            if path.endswith((".m3u", ".m3u8")) or any(
                word in path for word in ("playlist", "manifest")
            ):
                found.add(url)

    for match in REL_RE.findall(text):
        if base_url:
            found.add(urljoin(base_url, match))


def safe_public_url(url):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        try:
            ip = ipaddress.ip_address(parsed.hostname)
            return not (
                ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved
            )
        except ValueError:
            return True
    except Exception:
        return False


def main():
    print("Scanning:", SITE)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("request", lambda req: resources.add(req.url))

        def on_response(response):
            try:
                ctype = response.headers.get("content-type", "").lower()
                if any(x in ctype for x in (
                    "javascript", "json", "text", "mpegurl"
                )):
                    if response.request.resource_type in (
                        "document", "script", "xhr", "fetch"
                    ):
                        body = response.text()
                        if len(body) <= 3_000_000:
                            add_from_text(body, response.url)
            except Exception:
                pass

        page.on("response", on_response)

        try:
            page.goto(SITE, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(12000)
            add_from_text(page.content(), SITE)

            scripts = page.locator("script[src]").evaluate_all(
                "(els) => els.map(e => e.src)"
            )
            for script_url in scripts:
                resources.add(script_url)
                try:
                    response = page.request.get(script_url, timeout=20000)
                    if response.ok:
                        add_from_text(response.text(), script_url)
                except Exception as exc:
                    errors.append(f"Script scan: {exc}")
        except Exception as exc:
            errors.append(f"Browser scan: {exc}")
        finally:
            browser.close()

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; KhusbuPlaylistDetector/1.0)"
    })

    results = []
    for url in sorted(found):
        item = {
            "url": url,
            "status": "NOT_TESTED",
            "content_type": ""
        }
        if safe_public_url(url):
            try:
                response = session.get(
                    url,
                    headers={"Range": "bytes=0-1023"},
                    timeout=15,
                    stream=True,
                    allow_redirects=True
                )
                item["status"] = response.status_code
                item["content_type"] = response.headers.get("Content-Type", "")
                item["final_url"] = response.url
                response.close()
            except requests.RequestException as exc:
                item["status"] = "ERROR"
                item["error"] = str(exc)[:250]
        else:
            item["status"] = "SKIPPED_UNSAFE_OR_INVALID_URL"
        results.append(item)

    report = {
        "website": SITE,
        "total_detected": len(results),
        "results": results,
        "errors": errors
    }
    with open(JSON_FILE, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=False)

    with open(M3U_FILE, "w", encoding="utf-8") as file:
        file.write("#EXTM3U\n")
        for item in results:
            if isinstance(item["status"], int) and item["status"] in (200, 206):
                file.write(f"#EXTINF:-1,{urlparse(item['url']).path.split('/')[-1] or 'Detected stream'}\n")
                file.write(item["url"] + "\n")

    print(f"Detected candidates: {len(results)}")
    print(f"Saved: {JSON_FILE}, {M3U_FILE}")


if __name__ == "__main__":
    main()
