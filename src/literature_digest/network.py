"""Small bounded HTTP client. Never surface server bodies or credentials in errors."""

import http.client
import logging
import random
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

log = logging.getLogger(__name__)
MAX_RESPONSE = 8 * 1024 * 1024


class NetworkError(RuntimeError):
    def __init__(self, code, transient=False):
        self.code = code
        self.transient = transient
        super().__init__(code)


class AuthenticationError(NetworkError):
    pass


@dataclass
class Response:
    body: bytes
    headers: dict
    status: int = 200


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Credentials must never follow an API redirect. Only feed GET redirects.
        from .config import http_url

        if req.get_method() != "GET" or req.has_header("Authorization") or not http_url(newurl):
            raise NetworkError("unsafe_redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def retry_after(value):
    try:
        delay = float(value)
    except (ValueError, TypeError):
        try:
            delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return 0.0
    return max(0.0, delay)


class HTTPClient:
    def __init__(self, timeout=30, retries=3, opener=None, sleep=time.sleep):
        self.timeout, self.retries = timeout, retries
        self.opener = opener or build_opener(SafeRedirect()).open
        self.sleep = sleep

    def request(self, url, *, data=None, headers=None, observer=None):
        req = Request(
            url,
            data=data,
            headers={
                "User-Agent": "LiteratureDigest/1.0 (+https://github.com/KentoYana/LiteratureDigest)",
                **(headers or {}),
            },
        )
        for attempt in range(self.retries + 1):
            delay = min(30, 2**attempt) + random.uniform(0, 0.25)
            outcome = "network_error"
            try:
                with self.opener(req, timeout=self.timeout) as response:
                    body = response.read(MAX_RESPONSE + 1)
                    if len(body) > MAX_RESPONSE:
                        raise NetworkError("response_too_large")
                    return Response(body, dict(response.headers), response.status)
            except HTTPError as exc:
                status = exc.code
                outcome = f"http_{status}"
                header = exc.headers.get("Retry-After")
                exc.close()
                if observer:
                    observer(outcome, None)
                if status == 304:
                    return Response(b"", {}, 304)
                if status in {401, 403}:
                    raise AuthenticationError(outcome) from None
                if status != 429 and status < 500:
                    raise NetworkError(outcome) from None
                if header:
                    requested = retry_after(header)
                    # Do not retry early or block the batch for hours. Retry next run instead.
                    if requested > 300:
                        raise NetworkError("retry_after_deferred", transient=True) from None
                    delay = max(delay, requested)
            except NetworkError as exc:
                if observer:
                    observer(exc.code, None)
                raise
            except (
                URLError,
                TimeoutError,
                socket.timeout,
                ConnectionError,
                OSError,
                http.client.HTTPException,
            ):
                if observer:
                    observer(outcome, None)
            if attempt == self.retries:
                raise NetworkError(outcome, transient=True) from None
            log.info("HTTP retry attempt=%s delay=%.1fs", attempt + 1, delay)
            self.sleep(delay)
        raise AssertionError("unreachable")
