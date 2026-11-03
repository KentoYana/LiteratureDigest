"""Fetch feeds only. No publisher page fetching and no LLM calls."""

import calendar
import hashlib
import logging
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser

import feedparser
from defusedxml import ElementTree

from .database import now
from .network import HTTPClient, NetworkError
from .normalizer import normalize_doi, normalize_pmid

log = logging.getLogger(__name__)


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.ignored = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignored += 1
        if tag in {"p", "br", "div", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.ignored:
            self.ignored -= 1
        self.parts.append(" ")

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def plain(value):
    parser = PlainText()
    parser.feed(str(value or ""))
    return " ".join(unescape("".join(parser.parts)).split())


def parse_feed(body):
    # Reject DTD and entities before handing XML to the forgiving feed parser.
    ElementTree.fromstring(body, forbid_dtd=True)
    parsed = feedparser.parse(body)
    if not parsed.get("version"):
        raise ValueError("unsupported_feed")
    papers = []
    for entry in parsed.entries:
        links = entry.get("links", [])
        url = next(
            (
                x.get("href", "")
                for x in links
                if x.get("rel", "alternate") == "alternate"
                and x.get("type", "text/html") in {"text/html", "application/xhtml+xml"}
            ),
            entry.get("link", ""),
        )
        doi_raw = entry.get("prism_doi", "") or entry.get("dc_identifier", "")
        identifiers = [doi_raw, entry.get("id", ""), url]
        identifiers += [x.get("value", "") for x in entry.get("identifiers", [])]
        identifiers += [x.get("href", "") for x in links]
        doi_source = next((v for v in identifiers if normalize_doi(v)), "")
        if not doi_raw or not normalize_doi(doi_raw):
            doi_raw = doi_source
        pmid = normalize_pmid(entry.get("pubmed_pmid") or entry.get("prism_pmid") or "")
        pmid = pmid or next((normalize_pmid(v) for v in identifiers if normalize_pmid(v)), "")
        date = entry.get("published_parsed") or entry.get("updated_parsed")
        published = (
            datetime.fromtimestamp(calendar.timegm(date), timezone.utc).isoformat() if date else ""
        )
        abstract = entry.get("summary", "")
        if not abstract:
            abstract = next(
                (x.get("value", "") for x in entry.get("content", []) if x.get("value")), ""
            )
        paper = {
            "title": entry.get("title", ""),
            "authors": "; ".join(
                x.get("name", "") for x in entry.get("authors", []) if x.get("name")
            ),
            "journal": entry.get("prism_publicationname", "")
            or entry.get("source", {}).get("title", ""),
            "published": published,
            "doi": normalize_doi(doi_source),
            "doi_raw": doi_raw,
            "pmid": pmid,
            "url": url,
            "abstract": plain(abstract),
        }
        # Feed title is not assumed to be a journal name.
        source_id = entry.get("id") or url or hashlib.sha256(repr(paper).encode()).hexdigest()
        papers.append((str(source_id), paper))
    return papers


def collect(db, feeds, limit=None, http=None):
    http = http or HTTPClient()
    db.sync_feeds(feeds)
    stats = {"new": 0, "duplicates": 0, "feed_errors": 0}
    for feed in feeds:
        if not feed.get("enabled", True):
            continue
        stored = db.conn.execute("SELECT * FROM feeds WHERE id=?", (feed["id"],)).fetchone()
        headers = {}
        if stored["etag"]:
            headers["If-None-Match"] = stored["etag"]
        if stored["modified"]:
            headers["If-Modified-Since"] = stored["modified"]
        try:
            response = http.request(feed["url"], headers=headers)
            if response.status != 304:
                papers = parse_feed(response.body)
                selected = papers[:limit] if limit is not None else papers
                # A truncated feed must be fetched again to recover its remaining entries.
                truncated = len(selected) < len(papers)
                for source_id, paper in selected:
                    _, is_new = db.ingest(paper, feed["id"], source_id)
                    stats["new" if is_new else "duplicates"] += 1
                h = {k.lower(): v for k, v in response.headers.items()}
                with db.conn:
                    db.conn.execute(
                        "UPDATE feeds SET etag=?,modified=? WHERE id=?",
                        (
                            None if truncated else h.get("etag"),
                            None if truncated else h.get("last-modified"),
                            feed["id"],
                        ),
                    )
            with db.conn:
                db.conn.execute(
                    "UPDATE feeds SET last_fetch=?,error=NULL WHERE id=?", (now(), feed["id"])
                )
            log.info("Feed fetched id=%s", feed["id"])
        except Exception as exc:
            # Parse errors may contain raw XML. Store the class/code only.
            error = exc.code if isinstance(exc, NetworkError) else type(exc).__name__
            with db.conn:
                db.conn.execute(
                    "UPDATE feeds SET error=?,last_fetch=? WHERE id=?", (error, now(), feed["id"])
                )
            stats["feed_errors"] += 1
            log.warning("Feed fetch failed id=%s error=%s", feed["id"], error)
    log.info("Collection result %s", stats)
    return stats
