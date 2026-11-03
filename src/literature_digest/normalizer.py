"""Deterministic identifiers; never ask a language model to identify papers."""

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

DOI = re.compile(r"10\.\d{4,9}/[^\s<>\"]+", re.I)


def normalize_doi(value):
    value = unquote(str(value or "")).strip()
    if value.lower().startswith(
        ("http://doi.org/", "https://doi.org/", "http://dx.doi.org/", "https://dx.doi.org/")
    ):
        value = urlsplit(value).path
    match = DOI.search(value)
    return match.group(0).rstrip(".,;").lower() if match else ""


def normalize_pmid(value):
    value = str(value or "").strip()
    if value.isdigit():
        return str(int(value))
    match = re.search(r"(?:pubmed(?:\.ncbi\.nlm\.nih\.gov)?/|pmid\s*:?\s*)(\d+)", value, re.I)
    return match.group(1) if match else ""


def normalize_url(value):
    try:
        p = urlsplit(value or "")
        if p.scheme not in {"http", "https"} or not p.hostname:
            return ""
        port = p.port
        host = p.hostname.lower()
        if ":" in host:
            host = f"[{host}]"
        if port and (p.scheme, port) not in {("http", 80), ("https", 443)}:
            host += f":{port}"
        query = urlencode(
            sorted(
                (k, v)
                for k, v in parse_qsl(p.query, keep_blank_values=True)
                if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}
            )
        )
        return urlunsplit((p.scheme.lower(), host, p.path.rstrip("/") or "/", query, ""))
    except ValueError:
        return ""


def normalized_text(value):
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


def identities(paper, feed_id, source_id):
    result = []
    if paper.get("doi"):
        result.append("doi:" + paper["doi"])
    if paper.get("pmid"):
        result.append("pmid:" + paper["pmid"])
    if source_id:
        result.append("entry:" + feed_id + ":" + source_id)
    url = normalize_url(paper.get("url"))
    if url:
        result.append("url:" + url)
    # Exact bibliography only, with enough evidence to avoid title-only merging.
    if (
        paper.get("title")
        and paper.get("authors")
        and paper.get("published")
        and paper.get("journal")
    ):
        text = "\n".join(
            normalized_text(paper[k]) for k in ["title", "authors", "published", "journal"]
        )
        result.append("bib:" + hashlib.sha256(text.encode()).hexdigest())
    return result
