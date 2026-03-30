from __future__ import annotations

from collections import OrderedDict
from datetime import date
from typing import Iterable

from app.models import Article, normalize_title


def choose_better_article(existing: Article, incoming: Article) -> Article:
    score_existing = article_completeness(existing)
    score_incoming = article_completeness(incoming)
    better = incoming if score_incoming > score_existing else existing
    other = existing if better is incoming else incoming

    better.source_tags = sorted(set(existing.source_tags + incoming.source_tags))
    better.keywords = merge_unique(existing.keywords, incoming.keywords)
    better.authors = merge_unique(existing.authors, incoming.authors)
    better.corresponding_authors = merge_unique(existing.corresponding_authors, incoming.corresponding_authors)
    better.watch_author_matches = merge_unique(existing.watch_author_matches, incoming.watch_author_matches)
    better.watch_author_match_basis = merge_unique(existing.watch_author_match_basis, incoming.watch_author_match_basis)

    if not better.abstract and other.abstract:
        better.abstract = other.abstract
    if not better.doi and other.doi:
        better.doi = other.doi
    if not better.url and other.url:
        better.url = other.url
    if not better.pmid and other.pmid:
        better.pmid = other.pmid
    if not better.published and other.published:
        better.published = other.published

    warnings = merge_unique(existing.raw.get("warnings", []), incoming.raw.get("warnings", []))
    if warnings:
        better.raw["warnings"] = warnings
    if incoming.raw.get("author_query") and not better.raw.get("author_query"):
        better.raw["author_query"] = incoming.raw["author_query"]
    if existing.raw.get("author_query") and not better.raw.get("author_query"):
        better.raw["author_query"] = existing.raw["author_query"]

    return better


def article_completeness(article: Article) -> int:
    score = 0
    if article.abstract:
        score += 5
    if article.doi:
        score += 3
    if article.pmid:
        score += 2
    if article.published:
        score += 1
    if article.keywords:
        score += 2
    if article.authors:
        score += 1
    if article.corresponding_authors:
        score += 1
    return score


def dedupe_articles(articles: Iterable[Article]) -> list[Article]:
    ordered: "OrderedDict[str, Article]" = OrderedDict()
    for article in articles:
        key = article.doi.lower().strip() if article.doi else normalize_title(article.title)
        if not key:
            continue
        if key in ordered:
            ordered[key] = choose_better_article(ordered[key], article)
        else:
            ordered[key] = article
    return list(ordered.values())


def merge_unique(*lists: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for values in lists:
        for value in values:
            cleaned = value.strip()
            lowered = cleaned.lower()
            if cleaned and lowered not in seen:
                merged.append(cleaned)
                seen.add(lowered)
    return merged


def iso_date(value: date | None) -> str:
    return value.isoformat() if value else ""
