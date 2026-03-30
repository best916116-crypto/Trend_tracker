from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from typing import Any


@dataclass
class Article:
    title: str
    journal: str
    doi: str = ""
    url: str = ""
    abstract: str = ""
    published: date | None = None
    authors: list[str] = field(default_factory=list)
    corresponding_authors: list[str] = field(default_factory=list)
    watch_author_matches: list[str] = field(default_factory=list)
    watch_author_match_basis: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    source_tags: list[str] = field(default_factory=list)
    crossref_type: str = ""
    pmid: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def canonical_id(self) -> str:
        return self.doi.lower().strip() if self.doi else normalize_title(self.title)


@dataclass
class PrescoreResult:
    score: int
    lane: str
    matched_keywords: list[str]
    gate_matches: list[str]
    bucket_scores: dict[str, int]
    gate_passed: bool = False
    auto_pass: bool = False
    drop_reason: str = ""

    def should_watch(self, threshold: int = 0) -> bool:
        return self.gate_passed

    def should_review(self, threshold: int = 0) -> bool:
        return self.gate_passed


@dataclass
class LLMReview:
    llm_priority: int
    lane: str
    key_topics: list[str]
    paper_tldr_5_lines: list[str]
    why_it_matters_to_our_lab: str
    technical_takeaway: str
    best_fast_follower_title: str
    best_fast_follower_rationale: str
    fast_follower_type: str
    first_experiment: str
    time_to_first_readout_weeks: int
    resource_intensity: str
    ff_score: int
    ff_rank: str
    share_blurb_1line: str
    red_flags: list[str]
    decision: str


@dataclass
class ReviewedArticle:
    article: Article
    prescore: PrescoreResult
    review: LLMReview


@dataclass
class PipelineRun:
    run_started_at: datetime
    run_finished_at: datetime | None = None
    requested_days_back: int = 0
    actual_days_back: int = 0
    min_gated_papers: int = 0
    expansion_history: list[dict[str, Any]] = field(default_factory=list)
    collected_count: int = 0
    deduped_count: int = 0
    enriched_count: int = 0
    pubmed_failed_count: int = 0
    watchlist_count: int = 0
    reviewed_count: int = 0
    notion_created_count: int = 0
    notion_skipped_duplicates: int = 0
    journals: list[str] = field(default_factory=list)
    reviewed_articles: list[ReviewedArticle] = field(default_factory=list)
    dropped_articles: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return serialize_for_json(asdict(self))


def normalize_title(value: str) -> str:
    import re

    cleaned = value.lower().strip()
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def serialize_for_json(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value):
        return serialize_for_json(asdict(value))
    if isinstance(value, dict):
        return {k: serialize_for_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serialize_for_json(v) for v in value]
    return value
