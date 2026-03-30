from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.models import Article
from app.normalize import merge_unique

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


class PubMedClient:
    def __init__(
        self,
        email: str = "",
        api_key: str = "",
        tool: str = "genome-editing-literature-tracker",
        max_retries: int = 4,
        backoff_factor: float = 1.0,
    ) -> None:
        self.email = email
        self.api_key = api_key
        self.tool = tool
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": f"{tool}/0.3 ({email})" if email else f"{tool}/0.3",
                "Connection": "close",
                "Accept": "application/json, text/xml, */*",
            }
        )
        retry = Retry(
            total=max_retries,
            connect=max_retries,
            read=max_retries,
            status=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def enrich_article(self, article: Article, throttle_seconds: float = 0.34) -> Article:
        if article.abstract and article.pmid and article.keywords and article.authors:
            return article

        pmids: list[str] = []
        try:
            if article.doi:
                pmids = self.search_pmids_by_doi(article.doi)
                if throttle_seconds:
                    time.sleep(throttle_seconds)

            if not pmids:
                pmids = self.search_pmids_by_title(article.title)
                if throttle_seconds:
                    time.sleep(throttle_seconds)

            if not pmids:
                return article

            details = self.fetch_details(pmids[0])
            if not details:
                return article

            if details.get("abstract") and not article.abstract:
                article.abstract = details["abstract"]
            if details.get("pmid"):
                article.pmid = details["pmid"]
            if details.get("doi") and not article.doi:
                article.doi = details["doi"]
            article.keywords = merge_unique(article.keywords, details.get("keywords", []))
            article.authors = merge_unique(article.authors, details.get("authors", []))
            article.corresponding_authors = merge_unique(article.corresponding_authors, details.get("corresponding_authors", []))
            if "PubMed" not in article.source_tags:
                article.source_tags.append("PubMed")
            return article
        except (requests.RequestException, ET.ParseError, ValueError) as exc:
            article.raw.setdefault("warnings", []).append(f"pubmed_enrichment_failed: {exc}")
            return article

    def search_pmids_by_doi(self, doi: str) -> list[str]:
        term = f'"{doi}"[AID]'
        return self._esearch(term)

    def search_pmids_by_title(self, title: str) -> list[str]:
        compact = " ".join(title.split())
        term = f'"{compact}"[Title]'
        return self._esearch(term)

    def _esearch(self, term: str) -> list[str]:
        params = self._base_params()
        params.update(
            {
                "db": "pubmed",
                "retmode": "json",
                "retmax": 3,
                "term": term,
            }
        )
        response = self.session.get(ESEARCH_URL, params=params, timeout=60)
        response.raise_for_status()
        payload = response.json()
        return payload.get("esearchresult", {}).get("idlist", [])

    def fetch_details(self, pmid: str) -> dict[str, Any]:
        params = self._base_params()
        params.update(
            {
                "db": "pubmed",
                "id": pmid,
                "retmode": "xml",
            }
        )
        response = self.session.get(EFETCH_URL, params=params, timeout=60)
        response.raise_for_status()
        return parse_pubmed_xml(response.text)

    def _base_params(self) -> dict[str, str]:
        params = {"tool": self.tool}
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        return params


def parse_pubmed_xml(xml_text: str) -> dict[str, Any]:
    root = ET.fromstring(xml_text)
    article_node = root.find(".//PubmedArticle")
    if article_node is None:
        return {}

    pmid = article_node.findtext(".//PMID", default="").strip()
    abstract_fragments = [
        " ".join(elem.itertext()).strip()
        for elem in article_node.findall(".//Abstract/AbstractText")
    ]
    abstract = " ".join(fragment for fragment in abstract_fragments if fragment).strip()

    doi = ""
    for article_id in article_node.findall(".//PubmedData/ArticleIdList/ArticleId"):
        if article_id.attrib.get("IdType") == "doi":
            doi = (article_id.text or "").strip()
            break

    keywords = extract_pubmed_keywords(article_node)
    authors, corresponding_authors = extract_pubmed_authors(article_node)

    return {
        "pmid": pmid,
        "doi": doi,
        "abstract": abstract,
        "keywords": keywords,
        "authors": authors,
        "corresponding_authors": corresponding_authors,
    }


def extract_pubmed_keywords(article_node: ET.Element) -> list[str]:
    seen: set[str] = set()
    keywords: list[str] = []

    for elem in article_node.findall(".//KeywordList/Keyword"):
        text = " ".join(elem.itertext()).strip()
        lowered = text.lower()
        if text and lowered not in seen:
            keywords.append(text)
            seen.add(lowered)

    for elem in article_node.findall(".//MeshHeadingList/MeshHeading/DescriptorName"):
        text = " ".join(elem.itertext()).strip()
        lowered = text.lower()
        if text and lowered not in seen:
            keywords.append(text)
            seen.add(lowered)

    return keywords


def _normalize_person_name(name: str) -> str:
    name = (name or "").lower()
    name = re.sub(r"[.,()]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def extract_pubmed_authors(article_node: ET.Element) -> tuple[list[str], list[str]]:
    authors: list[str] = []
    corresponding_authors: list[str] = []
    seen_authors: set[str] = set()
    seen_corr: set[str] = set()

    for author in article_node.findall(".//AuthorList/Author"):
        collective = (author.findtext("CollectiveName", default="") or "").strip()
        last = (author.findtext("LastName", default="") or "").strip()
        fore = (author.findtext("ForeName", default="") or author.findtext("FirstName", default="") or "").strip()
        initials = (author.findtext("Initials", default="") or "").strip()

        name = collective or " ".join(part for part in [fore, last] if part).strip()
        if not name:
            name = " ".join(part for part in [initials, last] if part).strip()
        if not name:
            continue

        norm = _normalize_person_name(name)
        if norm not in seen_authors:
            authors.append(name)
            seen_authors.add(norm)

        affiliations = [
            " ".join(elem.itertext()).strip()
            for elem in author.findall(".//AffiliationInfo/Affiliation")
        ]
        if any("@" in aff for aff in affiliations):
            if norm not in seen_corr:
                corresponding_authors.append(name)
                seen_corr.add(norm)

    return authors, corresponding_authors
