import threading
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from xml.etree import ElementTree

import pytest

from literature_digest.publisher import CONTENT, publish
from literature_digest.server import make_server


def test_rss_atomic_and_guid(db, paths, settings, paper):
    aid, _ = db.ingest(paper, "a", "one")
    db.update(
        aid, status="completed", title_ja="日本語の研究記事", body_ja="結果 & <data> を紹介する。"
    )
    assert publish(db, paths, settings) == 1
    first = paths.feed.read_bytes()
    root = ElementTree.fromstring(first)
    guid = root.findtext("channel/item/guid")
    assert root.findtext("channel/item/link") == paper["url"]
    content = root.findtext(f"channel/item/{{{CONTENT}}}encoded")
    assert "&lt;data&gt;" in content and "10.1234/Test" in content
    publish(db, paths, settings)
    assert ElementTree.parse(paths.feed).findtext("channel/item/guid") == guid
    assert not list(paths.feed.parent.glob(".feed-*"))
    assert b"<content:encoded>" in first


def test_bibliography_only_sorted_limit(db, paths, settings, paper):
    one, _ = db.ingest(paper, "a", "one")
    db.update(one, status="skipped")
    two, _ = db.ingest(
        {
            **paper,
            "doi": "10.1234/two",
            "url": "https://example.org/two",
            "title": "Newer",
            "published": "2026-11-03T00:00:00+00:00",
        },
        "a",
        "two",
    )
    db.update(two, status="skipped")
    settings["publisher"]["limit"] = 1
    publish(db, paths, settings)
    root = ElementTree.parse(paths.feed)
    assert len(root.findall("channel/item")) == 1
    assert root.findtext("channel/item/title") == "Newer"


def test_http_scope(db, paths, settings, paper, tmp_path):
    aid, _ = db.ingest(paper, "a", "one")
    db.update(aid, status="skipped")
    publish(db, paths, settings)
    server = make_server(paths.feed, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with client.open(base + "/feed.xml") as r:
            assert r.headers.get_content_type() == "application/rss+xml"
            assert ElementTree.fromstring(r.read()).tag == "rss"
        for path in [
            "/",
            "/../config/settings.yaml",
            "/%2e%2e/config/settings.yaml",
            "/config/feeds.yaml",
            "/feed.xml?secret=key",
        ]:
            with pytest.raises(HTTPError) as exc:
                client.open(base + path)
            assert exc.value.code == 404
        with pytest.raises(HTTPError) as exc:
            client.open(Request(base + "/feed.xml", data=b"x"))
        assert exc.value.code == 501
        paths.feed.unlink()
        secret = tmp_path / "secret.txt"
        secret.write_text("private")
        paths.feed.symlink_to(secret)
        with pytest.raises(HTTPError) as exc:
            client.open(base + "/feed.xml")
        assert exc.value.code == 503
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    with pytest.raises(ValueError):
        make_server(paths.feed, 0, "0.0.0.0")
