"""PubMed E-utilities abstract lookup by exact PMID or DOI, <= 3 requests/sec."""

import json
import time
from urllib.parse import urlencode

from defusedxml import ElementTree

from .network import HTTPClient, NetworkError
from .normalizer import normalize_doi

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"


class PubMed:
    def __init__(self, email="", http=None, sleep=time.sleep, clock=time.monotonic):
        self.http = http or HTTPClient()
        self.email, self.sleep, self.clock = email, sleep, clock
        self.last = None

    def request(self, method, **params):
        if self.last is not None:
            self.sleep(max(0, 0.35 - (self.clock() - self.last)))
        self.last = self.clock()
        # Retry loop itself waits >=1 second, also respecting the rate limit.
        return self.http.request(
            BASE
            + method
            + "?"
            + urlencode({"db": "pubmed", "tool": "LiteratureDigest", "email": self.email, **params})
        ).body

    def abstract(self, paper):
        pmid = paper["pmid"]
        if not pmid and paper["doi"]:
            try:
                result = json.loads(
                    self.request(
                        "esearch.fcgi", term=f"{paper['doi']}[AID]", retmode="json", retmax=5
                    )
                )
                ids = result["esearchresult"]["idlist"]
            except (ValueError, KeyError, TypeError):
                raise NetworkError("pubmed_invalid_search", transient=True) from None
            if not isinstance(ids, list) or not all(
                isinstance(v, str) and v.isdigit() for v in ids
            ):
                raise NetworkError("pubmed_invalid_ids", transient=True)
            pmid = ",".join(ids)
        if not pmid:
            return ""
        try:
            root = ElementTree.fromstring(
                self.request("efetch.fcgi", id=pmid, retmode="xml"), forbid_dtd=False
            )
            if root.find(".//ERROR") is not None:
                raise NetworkError("pubmed_api_error", transient=True)
            for article in root.findall(".//PubmedArticle"):
                ids = article.findall(".//ArticleId")
                dois = {normalize_doi(x.text) for x in ids if x.get("IdType") == "doi"}
                found_pmid = article.findtext(".//PMID", "")
                if paper["doi"] and paper["doi"] not in dois:
                    continue
                if paper["pmid"] and found_pmid != paper["pmid"]:
                    continue
                parts = []
                for text in article.findall(".//Abstract/AbstractText"):
                    label = text.get("Label")
                    parts.append((label + ": " if label else "") + "".join(text.itertext()))
                return "\n".join(parts).strip()
        except (ElementTree.ParseError, ValueError):
            raise NetworkError("pubmed_invalid_xml", transient=True) from None
        return ""
