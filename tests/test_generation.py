import pytest
from test_api import BODY

from literature_digest.generator import generate
from literature_digest.metadata import PubMed
from literature_digest.network import AuthenticationError, NetworkError, Response
from literature_digest.sarashina import Digest, OutputError


class Client:
    def __init__(self):
        self.calls = []

    def generate(self, paper, prompt, correction=False):
        self.calls.append(correction)
        return Digest("新しい研究の知見", BODY, "sarashina3-mini")


def test_generation_idempotence(db, paths, settings, paper):
    aid, _ = db.ingest(paper, "a", "one")
    client = Client()
    assert generate(db, paths, settings, client_factory=lambda _: client)["completed"] == 1
    assert (
        generate(db, paths, settings, client_factory=lambda _: pytest.fail("no pending"))[
            "completed"
        ]
        == 0
    )
    stored = db.conn.execute("SELECT * FROM articles WHERE id=?", (aid,)).fetchone()
    assert stored["prompt_version"].startswith("v1-sha256:")
    assert stored["model"] == "sarashina3-mini" and stored["generated_at"]
    assert len(client.calls) == 1


def test_processing_recovery(db, paths, settings, paper):
    aid, _ = db.ingest(paper, "a", "one")
    db.claim(aid)
    assert generate(db, paths, settings, client_factory=lambda _: Client())["completed"] == 1


def test_missing_abstract_no_api(db, paths, settings, paper):
    db.ingest({**paper, "abstract": ""}, "a", "one")
    stats = generate(db, paths, settings, client_factory=lambda _: pytest.fail("must skip"))
    assert stats["skipped"] == 1


def test_length_retries_once(db, paths, settings, paper):
    db.ingest(paper, "a", "one")

    class Retry(Client):
        def generate(self, paper, prompt, correction=False):
            self.calls.append(correction)
            raise OutputError("invalid_length")

    client = Retry()
    assert generate(db, paths, settings, client_factory=lambda _: client)["failed"] == 1
    assert client.calls == [False, True]


def test_transient_failed_recovers_next_run(db, paths, settings, paper):
    db.ingest(paper, "a", "one")

    class Retry(Client):
        def generate(self, *a, **k):
            raise NetworkError("http_500", transient=True)

    assert generate(db, paths, settings, client_factory=lambda _: Retry())["failed"] == 1
    assert generate(db, paths, settings, client_factory=lambda _: Client())["completed"] == 1


def test_auth_failure_stops_batch(db, paths, settings, paper):
    db.ingest(paper, "a", "one")
    db.ingest({**paper, "doi": "10.1234/two", "url": "https://example.org/2"}, "a", "two")

    class Auth(Client):
        def generate(self, *a, **k):
            raise AuthenticationError("http_401")

    assert generate(db, paths, settings, client_factory=lambda _: Auth())["failed"] == 1
    assert db.status()["articles"]["pending"] == 1


def test_metadata_verified_doi(paper):
    class HTTP:
        def __init__(self):
            self.calls = []

        def request(self, url):
            self.calls.append(url)
            if "esearch" in url:
                return Response(b'{"esearchresult":{"idlist":["123"]}}', {})
            return Response(
                b'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><Abstract><AbstractText Label="RESULTS">Exact abstract.</AbstractText></Abstract></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1234/test</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>',
                {},
            )

    http = HTTP()
    sleeps = []
    m = PubMed(http=http, sleep=sleeps.append)
    assert m.abstract(paper) == "RESULTS: Exact abstract."
    assert len(http.calls) == 2 and sleeps[0] > 0
    assert PubMed(http=http, sleep=lambda _: None).abstract({**paper, "doi": "10.1234/WRONG"}) == ""


def test_metadata_failure_remains_retryable(db, paths, settings, paper):
    db.ingest({**paper, "abstract": ""}, "a", "one")
    settings["metadata"]["pubmed"] = True

    class Metadata:
        def abstract(self, paper):
            raise NetworkError("http_500", True)

    generate(db, paths, settings, metadata=Metadata())
    row = db.pending(1)[0]
    assert row["status"] == "failed" and row["metadata_checked"] == 0
