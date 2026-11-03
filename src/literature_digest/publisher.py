"""Safe UTF-8 RSS, stable stored GUIDs and atomic replacement."""

import html
import os
import re
import tempfile
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.etree import ElementTree as ET

from .config import http_url

CONTENT = "http://purl.org/rss/1.0/modules/content/"
DC = "http://purl.org/dc/elements/1.1/"
ET.register_namespace("content", CONTENT)
ET.register_namespace("dc", DC)


def xml_text(value):
    # XML 1.0 permits only these characters. Keep originals untouched in SQLite.
    return re.sub(
        r"[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]", "", str(value or "")
    )


def rss_date(value):
    try:
        date = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        date = datetime.now(timezone.utc)
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return format_datetime(date.astimezone(timezone.utc), usegmt=True)


def build_rss(articles, settings):
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")

    def add(parent, name, value):
        element = ET.SubElement(parent, name)
        element.text = xml_text(value)
        return element

    add(channel, "title", settings["publisher"]["title"])
    add(channel, "link", f"http://127.0.0.1:{settings['server']['port']}/feed.xml")
    add(channel, "description", settings["publisher"]["description"])
    add(channel, "language", "ja")
    for a in articles:
        item = ET.SubElement(channel, "item")
        title = a["title_ja"] if a["status"] == "completed" else a["title"]
        add(item, "title", title or "（原題なし）")
        add(item, "guid", a["guid"]).set("isPermaLink", "false")
        if http_url(a["url"]):
            add(item, "link", a["url"])
        add(item, "pubDate", rss_date(a["published"] or a["fetched_at"]))
        body = (
            a["body_ja"]
            if a["status"] == "completed"
            else "抄録を取得できないため、書誌情報のみ配信しています。"
        )
        content = "<p>" + html.escape(body).replace("\n", "<br />") + "</p><dl>"
        for label, field in [
            ("原題", "title"),
            ("著者", "authors"),
            ("雑誌", "journal"),
            ("DOI", "doi_raw"),
            ("PMID", "pmid"),
            ("原著URL", "url"),
        ]:
            value = a[field]
            if field == "doi_raw":
                value = value or a["doi"]
            if value:
                content += f"<dt>{label}</dt><dd>{html.escape(xml_text(value))}</dd>"
        content += "</dl>"
        if a["status"] == "completed":
            content += "<p>抄録に基づくAI生成記事。詳細・正確性は原著をご確認ください。</p>"
        add(item, "description", body)
        add(item, f"{{{CONTENT}}}encoded", content)
        add(item, f"{{{DC}}}title", a["title"])
        if a["authors"]:
            add(item, f"{{{DC}}}creator", a["authors"])
        if a["doi"]:
            add(item, f"{{{DC}}}identifier", "doi:" + a["doi"])
        if a["journal"]:
            add(item, f"{{{DC}}}source", a["journal"])
    result = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    ET.fromstring(result)
    return result


def publish(db, paths, settings):
    articles = db.published(settings["publisher"]["limit"])
    body = build_rss(articles, settings)
    paths.feed.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=paths.feed.parent, prefix=".feed-", delete=False
        ) as out:
            temp = out.name
            out.write(body)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, paths.feed)
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)
    return len(articles)
