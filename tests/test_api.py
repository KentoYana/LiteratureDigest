import io
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from literature_digest.network import (
    HTTPClient,
    NetworkError,
    Response,
    SafeRedirect,
    retry_after,
)
from literature_digest.sarashina import OutputError, Sarashina, validate_output

BODY = "研究の背景と結果を正確に伝える記事である。" * 12


def response(content=None, **overrides):
    value = {
        "model": "sarashina3-mini",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(
                        content or {"title_ja": "研究の新たな知見", "body_ja": BODY}
                    )
                },
            }
        ],
        "usage": {"total_tokens": 123},
    }
    return {**value, **overrides}


class FakeHTTP:
    def __init__(self, value):
        self.value = value
        self.kwargs = None

    def request(self, url, **kwargs):
        self.kwargs = kwargs
        return Response(json.dumps(self.value).encode(), {})


def test_request_and_usage(settings, paper):
    calls = []
    http = FakeHTTP(response())
    client = Sarashina(
        "secret-key", settings["llm"], observer=lambda *a: calls.append(a), http=http
    )
    digest = client.generate(paper, "trusted prompt")
    assert digest.body_ja == BODY
    payload = json.loads(http.kwargs["data"])
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert payload["max_completion_tokens"] == 700
    assert payload["stream"] is False and payload["n"] == 1
    assert "secret-key" not in json.dumps(payload)
    assert calls == [("completed", {"total_tokens": 123})]


@pytest.mark.parametrize(
    "value,code",
    [
        ([], "invalid_structure"),
        ({}, "invalid_structure"),
        ({"title_ja": "Title", "body_ja": BODY}, "missing_japanese_text"),
        ({"title_ja": "見出し", "body_ja": "短い"}, "invalid_length"),
        ({"title_ja": "見出し", "body_ja": BODY + "<script>"}, "invalid_markup"),
        ({"title_ja": "見出し", "body_ja": BODY + "\x00"}, "invalid_markup"),
        ({"title_ja": "見出し", "body_ja": None}, "missing_japanese_text"),
    ],
)
def test_invalid_output(value, code):
    with pytest.raises(OutputError, match=code):
        validate_output(value)


@pytest.mark.parametrize(
    "value",
    [
        {"choices": []},
        {"choices": None},
        {"choices": [None]},
        {"choices": [{"finish_reason": "length"}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": "not json"}}]},
        {"choices": [{"finish_reason": "stop", "message": None}]},
    ],
)
def test_invalid_responses(settings, paper, value):
    client = Sarashina("key", settings["llm"], http=FakeHTTP(value))
    with pytest.raises(OutputError):
        client.generate(paper, "prompt")


def test_malformed_json(settings, paper):
    class Bad:
        def request(self, *a, **k):
            return Response(b"no json", {})

    with pytest.raises(OutputError, match="invalid_json"):
        Sarashina("key", settings["llm"], http=Bad()).generate(paper, "prompt")


def error(status, retry=None):
    return HTTPError(
        "https://api.example.org",
        status,
        "secret-key should not leak",
        {"Retry-After": retry} if retry else {},
        io.BytesIO(b"secret-key in body"),
    )


@pytest.mark.parametrize(
    "failure", [TimeoutError(), URLError("secret-key"), ConnectionResetError(), error(500)]
)
def test_transient_bounded(failure):
    calls, sleeps = [], []

    def opener(*a, **k):
        calls.append(1)
        raise failure

    with pytest.raises(NetworkError) as exc:
        HTTPClient(retries=2, opener=opener, sleep=sleeps.append).request("https://api.example.org")
    assert len(calls) == 3 and len(sleeps) == 2
    assert "secret-key" not in str(exc.value)


def test_429_retry_after():
    attempts, sleeps = [], []

    def opener(*a, **k):
        attempts.append(1)
        raise error(429, "17")

    with pytest.raises(NetworkError):
        HTTPClient(retries=1, opener=opener, sleep=sleeps.append).request("https://api.example.org")
    assert len(attempts) == 2 and sleeps[0] >= 17
    assert retry_after("bad") == 0
    assert retry_after("Tue, 01 Jan 2000 00:00:00 GMT") == 0


def test_long_cooldown_deferred():
    def opener(*a, **k):
        raise error(429, "3600")

    with pytest.raises(NetworkError, match="retry_after_deferred"):
        HTTPClient(opener=opener, sleep=lambda x: pytest.fail("must not sleep")).request(
            "https://api.example.org"
        )


@pytest.mark.parametrize("code", [401, 403, 400])
def test_no_retry_for_credentials_or_bad_requests(code):
    calls = []

    def opener(*a, **k):
        calls.append(1)
        raise error(code)

    with pytest.raises(NetworkError):
        HTTPClient(opener=opener).request("https://api.example.org")
    assert len(calls) == 1


def test_no_credential_redirect():
    redirect = SafeRedirect()
    req = Request("https://api.example.org", data=b"{}", headers={"Authorization": "Bearer secret"})
    with pytest.raises(NetworkError, match="unsafe_redirect"):
        redirect.redirect_request(req, None, 307, "", {}, "https://evil.example.org")
