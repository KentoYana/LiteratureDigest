from pathlib import Path

import pytest

from literature_digest.config import Paths, initialize, load_settings
from literature_digest.database import Database


@pytest.fixture
def paths(tmp_path):
    p = Paths.resolve(tmp_path / "home")
    initialize(p)
    return p


@pytest.fixture
def settings(paths):
    s = load_settings(paths)
    s["metadata"]["pubmed"] = False
    return s


@pytest.fixture
def db(paths):
    value = Database(paths.db)
    value.sync_feeds(
        [
            {"id": "a", "name": "A", "url": "https://example.org/a"},
            {"id": "b", "name": "B", "url": "https://example.org/b"},
        ]
    )
    yield value
    value.close()


@pytest.fixture
def paper():
    return {
        "title": "Research & <results>",
        "authors": "A; B",
        "journal": "Journal",
        "published": "2026-11-02T09:00:00+00:00",
        "doi": "10.1234/test",
        "doi_raw": "10.1234/Test",
        "pmid": "",
        "url": "https://example.org/paper?a=1&b=2",
        "abstract": "Evidence from the experiment.",
    }


@pytest.fixture
def fixture():
    return lambda name: (Path(__file__).parent / "fixtures" / name).read_bytes()
