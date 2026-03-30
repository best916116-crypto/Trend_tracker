from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta
from typing import Any

import requests

from app.keywords import DEFAULT_JOURNAL_PRESET, resolve_journal_preset
from app.models import Article

CROSSREF_BASE = "https://api.crossref.org/works"


class CrossrefClient:
    def __init__(self, mailto: str = "") -> None:
        self.mailto = mailto
        user_agent = "genome-editing-literature-tracker/0.6"
        if mailto:
            user_agent += f" (mailto:{mailto})"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def fetch_recent_cns_articles(
        self,
        days_back: int,
        rows_per_journal: int = 50,
        journals: list[str] | None = None,
        journal_preset: str | None = None,
    ) -> list[Article]:
        journals = journals or resolve_journal_preset(journal_preset or DEFAULT_JOURNAL_PRESET)
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=days_back)

        collected: list[Article] = []
        for journal in journals:
            collected.extend(
                self._fetch_recent_journal_articles(
                    journal=journal,
                    start_date=start_date,
                    end_date=end_date,
                    rows=rows_per_journal,
                )
            )
        return collected

    def fetch_recent_author_articles(
        self,
        days_back: int,
        author_names: list[str],
        rows_per_author: int = 10,
    ) -> list[Article]:
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=days_back)

        collected: list[Article] = []
        for author_name in author_names:
            collected.extend(
                self._fetch_recent_author_query_articles(
                    author_name=author_name,
                    start_date=start_date,
                    end_date=end_date,
                    rows=rows_per_author,
                )
            )
        return collected

    def _fetch_recent_journal_articles(
        self,
        journal: str,
        start_date: date,
        end_date: date,
        rows: int,
    ) -> list[Article]:
        filters = [
            f"container-title:{journal}",
            "type:journal-article",
            f"from-pub-date:{start_date.isoformat()}",
            f"until-pub-date:{end_date.isoformat()}",
        ]
        params: dict[str, Any] = {
            "filter": ",".join(filters),
            "rows": rows,
            "sort": "published",
            "order": "desc",
        }
        if self.mailto:
            params["mailto"] = self.mailto

        response = self.session.get(CROSSREF_BASE, params=params, timeout=60)
        response.raise_for_status()
        payload = response.json()
        items = payload.get("message", {}).get("items", [])

        articles: list[Article] = []
        for item in items:
            article = self._parse_item(item)
            if article:
                articles.append(article)
        return articles

    def _fetch_recent_author_query_articles(
        self,
        author_name: str,
        start_date: date,
        end_date: date,
        rows: int,
    ) -> list[Article]:
        filters = [
            "type:journal-article",
            f"from-pub-date:{start_date.isoformat()}",
            f"until-pub-date:{end_date.isoformat()}",
        ]
        params: dict[str, Any] = {
            "filter": ",".join(filters),
            "query.author": author_name,
            "rows": rows,
            "sort": "published",
            "order": "desc",
        }
        if self.mailto:
            params["mailto"] = self.mailto

        response = self.session.get(CROSSREF_BASE, params=params, timeout=60)
        response.raise_for_status()
        payload = response.json()
        items = payload.get("message", {}).get("items", [])

        articles: list[Article] = []
        for item in items:
            article = self._parse_item(item)
            if article:
                if "Crossref Author Watch" not in article.source_tags:
                    article.source_tags.append("Crossref Author Watch")
                article.raw["author_query"] = author_name
                articles.append(article)
        return articles

    def _parse_item(self, item: dict[str, Any]) -> Article | None:
        title_list = item.get("title") or []
        title = title_list[0].strip() if title_list else ""
        if not title:
            return None

        journal_list = item.get("container-title") or []
        journal = journal_list[0].strip() if journal_list else ""
        abstract = clean_crossref_abstract(item.get("abstract", ""))
        published = extract_crossref_date(item)
        authors = [format_author(author) for author in item.get("author", [])]
        doi = item.get("DOI", "") or ""
        url = item.get("URL", "") or (f"https://doi.org/{doi}" if doi else "")
        keywords = extract_crossref_keywords(item)

        return Article(
            title=title,
            journal=journal,
            doi=doi,
            url=url,
            abstract=abstract,
            published=published,
            authors=[a for a in authors if a],
            keywords=keywords,
            source_tags=["Crossref"],
            crossref_type=item.get("type", "") or "",
            raw=item,
        )


def format_author(author: dict[str, Any]) -> str:
    given = (author.get("given") or "").strip()
    family = (author.get("family") or "").strip()
    full = f"{given} {family}".strip()
    return full


def clean_crossref_abstract(value: str) -> str:
    if not value:
        return ""
    text = html.unescape(value)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_crossref_keywords(item: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    keywords: list[str] = []
    for field_name in ["subject", "keyword"]:
        values = item.get(field_name) or []
        if isinstance(values, str):
            values = [values]
        for value in values:
            cleaned = re.sub(r"\s+", " ", str(value)).strip()
            lowered = cleaned.lower()
            if cleaned and lowered not in seen:
                keywords.append(cleaned)
                seen.add(lowered)
    return keywords


def extract_crossref_date(item: dict[str, Any]) -> date | None:
    for key in ["published-online", "published-print", "issued", "created"]:
        parts = item.get(key, {}).get("date-parts", [])
        if parts and parts[0]:
            year = parts[0][0]
            month = parts[0][1] if len(parts[0]) > 1 else 1
            day = parts[0][2] if len(parts[0]) > 2 else 1
            try:
                return date(year, month, day)
            except ValueError:
                continue
    return None
