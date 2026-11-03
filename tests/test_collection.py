import pytest

from literature_digest.collector import collect, parse_feed, plain
from literature_digest.database import Database
from literature_digest.network import NetworkError, Response
from literature_digest.normalizer import normalize_doi, normalize_pmid, normalize_url


@pytest.mark.parametrize(
    "value",
    [
        "10.1234/ABC",
        "doi:10.1234/ABC",
        "https://doi.org/10.1234/ABC",
        "http://dx.doi.org/10.1234/ABC",
        " DOI: 10.1234/ABC ",
    ],
)
def test_doi(value):
    assert normalize_doi(value) == "10.1234/abc"


def test_identifiers():
    assert normalize_doi("no DOI") == ""
    assert normalize_doi("https://doi.org/10.1234/ABC%2Fdef") == "10.1234/abc/def"
    assert normalize_pmid("PMID: 123") == "123"
    assert normalize_pmid("https://pubmed.ncbi.nlm.nih.gov/123/") == "123"
    assert (
        normalize_url("https://EXAMPLE.org:443/p/?utm_source=x&b=2&a=1#frag")
        == "https://example.org/p?a=1&b=2"
    )
    assert normalize_url("javascript:alert(1)") == ""


def test_parse_rss_atom(fixture):
    rss = parse_feed(fixture("rss.xml"))
    atom = parse_feed(fixture("atom.xml"))
    assert rss[0][1]["doi"] == atom[0][1]["doi"] == "10.1234/abc"
    assert rss[0][1]["authors"] == "Alice"
    assert rss[0][1]["journal"] == "Actual Journal"
    assert rss[0][1]["abstract"] == "An abstract & results."
    assert rss[0][1]["published"] == "2026-11-02T09:00:00+00:00"
    assert rss[1][1]["abstract"] == ""
    assert rss[1][1]["pmid"] == "12345678"
    assert atom[0][1]["abstract"] == "Atom abstract."
    assert atom[0][1]["journal"] == ""


def test_reject_entities():
    with pytest.raises(Exception):
        parse_feed(
            b'<!DOCTYPE rss [<!ENTITY s "secret">]><rss version="2.0"><channel><title>&s;</title></channel></rss>'
        )
    assert plain("<p>Valid</p><script>bad()</script><style>secret</style>") == "Valid"


def test_dedup_and_persistence(db, paths, paper):
    aid, new = db.ingest(paper, "a", "early")
    assert new
    assert db.ingest(paper, "b", "version-of-record") == (aid, False)
    assert db.ingest(paper, "a", "early") == (aid, False)
    assert db.status()["articles"]["pending"] == 1
    assert db.conn.execute("SELECT count(*) FROM entries").fetchone()[0] == 2
    fresh = Database(paths.db)
    try:
        assert fresh.conn.execute("SELECT doi_raw FROM articles").fetchone()[0] == "10.1234/Test"
    finally:
        fresh.close()


def test_conflicting_doi_not_merged(db, paper):
    one, _ = db.ingest(paper, "a", "one")
    two, new = db.ingest({**paper, "doi": "10.1234/other"}, "b", "two")
    assert new and one != two
    # Repeated conflicted URL still resolves by its correct DOI.
    assert db.ingest({**paper, "doi": "10.1234/other"}, "b", "two") == (two, False)


def test_enrich_skipped_without_changing_completed(db, paper):
    aid, _ = db.ingest({**paper, "abstract": "", "doi": "", "doi_raw": ""}, "a", "one")
    db.update(aid, status="skipped")
    assert db.ingest(paper, "b", "two") == (aid, False)
    assert db.pending(10)[0]["doi"] == paper["doi"]
    db.update(aid, status="completed", title_ja="日本語", body_ja="本文")
    db.ingest({**paper, "title": "Changed", "url": "https://other.example.org"}, "a", "three")
    stored = db.conn.execute("SELECT * FROM articles").fetchone()
    assert stored["title"] == paper["title"] and stored["status"] == "completed"


def test_fallback_needs_evidence(db, paper):
    sparse = {**paper, "doi": "", "pmid": "", "url": "", "authors": ""}
    assert db.ingest(sparse, "a", "1")[1]
    assert db.ingest(sparse, "b", "2")[1]
    full = {**sparse, "authors": "Author"}
    aid, _ = db.ingest(full, "a", "3")
    assert db.ingest(full, "b", "4") == (aid, False)


def test_conditional_fetch_and_limit(db, fixture):
    class HTTP:
        def __init__(self):
            self.headers = []

        def request(self, url, headers):
            self.headers.append(headers)
            return Response(fixture("rss.xml"), {"ETag": '"v1"'})

    http = HTTP()
    feeds = [{"id": "a", "name": "A", "url": "https://example.org/a"}]
    assert collect(db, feeds, limit=1, http=http)["new"] == 1
    assert db.conn.execute("SELECT etag FROM feeds WHERE id='a'").fetchone()[0] is None
    assert collect(db, feeds, http=http)["new"] == 1
    assert collect(db, feeds, http=http)["duplicates"] == 2
    assert http.headers[-1]["If-None-Match"] == '"v1"'


def test_feed_failure_isolated(db):
    class Bad:
        def request(self, *args, **kwargs):
            raise NetworkError("http_500")

    stats = collect(db, [{"id": "a", "name": "A", "url": "https://example.org/a"}], http=Bad())
    assert stats["feed_errors"] == 1
    assert db.status()["feed_errors"] == 1


def test_doi_url_query_is_not_identifier():
    assert normalize_doi("https://doi.org/10.1234/ABC?utm_source=rss#top") == "10.1234/abc"


def test_later_doi_bridges_entries_preserving_completed_guid(db, paper):
    early, _ = db.ingest({**paper, "doi": "", "doi_raw": ""}, "a", "early")
    db.update(early, status="completed", title_ja="早期の記事", body_ja="保存する本文")
    guid = db.conn.execute("SELECT guid FROM articles WHERE id=?", (early,)).fetchone()[0]
    later, _ = db.ingest(
        {**paper, "url": "https://example.org/version", "published": "2026-11-03T00:00:00+00:00"},
        "b",
        "later",
    )
    assert early != later
    db.api_call(later, "sarashina3-mini", "completed", {"total_tokens": 10})
    assert db.ingest(paper, "a", "early") == (early, False)
    assert db.conn.execute("SELECT count(*) FROM articles").fetchone()[0] == 1
    row = db.conn.execute("SELECT * FROM articles").fetchone()
    assert row["guid"] == guid and row["title_ja"] == "早期の記事"
    assert row["doi"] == paper["doi"]
    assert (
        db.conn.execute("SELECT count(*) FROM entries WHERE article_id=?", (early,)).fetchone()[0]
        == 2
    )
    assert db.conn.execute("SELECT article_id FROM api_calls").fetchone()[0] == early
    assert db.ingest(
        {**paper, "url": "https://example.org/version", "published": "2026-11-03T00:00:00+00:00"},
        "b",
        "later",
    ) == (
        early,
        False,
    )


def test_conflicting_candidates_are_never_bridged(db, paper):
    first, _ = db.ingest(paper, "a", "first")
    second, _ = db.ingest(
        {**paper, "doi": "10.1234/other", "url": "https://example.org/other"}, "b", "second"
    )
    db.ingest({**paper, "doi": "10.1234/other"}, "a", "first")
    assert db.conn.execute("SELECT count(*) FROM articles").fetchone()[0] == 2
    assert first != second


def test_arxiv_explicit_doi():
    data = b'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom"><title>arXiv</title><entry><id>http://arxiv.org/abs/1234.5678</id><title>Study</title><arxiv:doi>10.1234/ABC</arxiv:doi></entry></feed>'
    assert parse_feed(data)[0][1]["doi"] == "10.1234/abc"
