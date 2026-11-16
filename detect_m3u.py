import re
import json
import html
import urllib.request
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

SITE = "https://maruf-tv.blogspot.com/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PlaylistDetector/1.0)"}
MAX_BYTES = 2_000_000

class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for key in ("src", "href", "data-src", "data-url", "data-href"):
            if attrs.get(key):
                self.links.append(attrs[key])

def fetch(url, limit=MAX_BYTES):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=25) as response:
        data = response.read(limit)
        content_type = response.headers.get("Content-Type", "")
        final_url = response.geturl()
    return data.decode("utf-8", errors="ignore"), content_type, final_url

def absolute(url, base=SITE):
    return urllib.parse.urljoin(base, html.unescape(url.strip()))

def main():
    queue = [SITE]
    scanned = set()
    candidates = set()
    errors = []

    while queue and len(scanned) < 40:
        source = queue.pop(0)
        if source in scanned:
            continue
        scanned.add(source)

        try:
            content, content_type, final_url = fetch(source)
            parser = PageParser()
            parser.feed(content)

            for raw in parser.links:
                link = absolute(raw, final_url)
                if not link.startswith(("http://", "https://")):
                    continue
                if re.search(r"\\.m3u8?(?:[?#]|$)", link, re.I):
                    candidates.add(link)
                path = urllib.parse.urlparse(link).path.lower()
                if path.endswith((".js", ".html", ".htm")) and link not in scanned and link not in queue:
                    queue.append(link)

            content = html.unescape(content).replace(r"\\/", "/")
            urls = re.findall(rr'''https?://[^\"'\\\\\\s<>]+''', content, re.I)
            for url in urls:
                url = url.rstrip("),;]}")
                if re.search(r"\\.m3u8?(?:[?#]|$)|[?&](?:type|output)=m3u", url, re.I):
                    candidates.add(url)
                path = urllib.parse.urlparse(url).path.lower()
                if path.endswith((".js", ".html", ".htm")) and url not in scanned and url not in queue:
                    queue.append(url)

        except Exception as exc:
            errors.append({"source": source, "error": str(exc)[:300]})

    results = []
    for url in sorted(candidates):
        item = {"url": url}
        try:
            body, content_type, final_url = fetch(url, 1_000_000)
            item["final_url"] = final_url
            item["content_type"] = content_type
            item["extinf_count"] = body.count("#EXTINF")
            item["status"] = "VALID_PLAYLIST" if "#EXTM3U" in body[:20000] else "REACHABLE_NOT_CONFIRMED"
        except Exception as exc:
            item["status"] = "FETCH_ERROR"
            item["error"] = str(exc)[:300]
        results.append(item)

    report = {
        "website": SITE,
        "pages_scanned": len(scanned),
        "candidates_found": len(candidates),
        "results": results,
        "scan_errors": errors,
        "note": "Reachable does not guarantee playable. DRM/login restrictions are not bypassed."
    }
    Path("detected_links.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = ["MARUF TV PLAYLIST SCAN", f"Website: {SITE}",
             f"Pages scanned: {len(scanned)}", f"Candidates found: {len(candidates)}", ""]
    for item in results:
        lines.append(f"[{item['status']}] {item['url']}")
        if "extinf_count" in item:
            lines.append(f"  EXTINF entries: {item['extinf_count']}")
    lines.append(f"Scan errors: {len(errors)}")
    Path("report.txt").write_text("\\n".join(lines) + "\\n", encoding="utf-8")
    print("\\n".join(lines))

if __name__ == "__main__":
    main()
