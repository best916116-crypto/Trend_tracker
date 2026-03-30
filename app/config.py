from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

from app.keywords import DEFAULT_JOURNAL_PRESET

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

ReasoningEffort = Literal["none", "low", "medium", "high"]
Verbosity = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class Config:
    openai_api_key: str
    openai_model: str = "gpt-5.4-mini"
    openai_reasoning_effort: ReasoningEffort = "none"
    openai_text_verbosity: Verbosity = "low"
    reader_language: str = "ko"

    notion_api_key: str = ""
    notion_database_id: str = ""
    notion_version: str = "2026-03-11"

    timezone: str = "Asia/Seoul"
    days_back: int = 7
    llm_review_limit: int = 10
    min_gated_papers: int = 5
    max_days_back: int = 35
    expand_step_days: int = 7
    crossref_rows_per_journal: int = 50
    crossref_rows_per_author: int = 10
    journal_preset: str = DEFAULT_JOURNAL_PRESET

    crossref_mailto: str = ""
    ncbi_email: str = ""
    ncbi_api_key: str = ""
    ncbi_tool: str = "genome-editing-literature-tracker"
    enable_pubmed_enrichment: bool = True
    pubmed_max_retries: int = 4
    pubmed_backoff_factor: float = 1.0

    @property
    def notion_enabled(self) -> bool:
        return bool(self.notion_api_key and self.notion_database_id)


def _getenv(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value or ""


def _getenv_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_config(require_openai: bool = True) -> Config:
    return Config(
        openai_api_key=_getenv("OPENAI_API_KEY", "", required=require_openai),
        openai_model=_getenv("OPENAI_MODEL", "gpt-5.4-mini"),
        openai_reasoning_effort=_getenv("OPENAI_REASONING_EFFORT", "none"),
        openai_text_verbosity=_getenv("OPENAI_TEXT_VERBOSITY", "low"),
        reader_language=_getenv("READER_LANGUAGE", "ko"),
        notion_api_key=_getenv("NOTION_API_KEY", ""),
        notion_database_id=_getenv("NOTION_DATABASE_ID", ""),
        notion_version=_getenv("NOTION_VERSION", "2026-03-11"),
        timezone=_getenv("TIMEZONE", "Asia/Seoul"),
        days_back=int(_getenv("DAYS_BACK", "7")),
        llm_review_limit=int(_getenv("LLM_REVIEW_LIMIT", "10")),
        min_gated_papers=int(_getenv("MIN_GATED_PAPERS", "5")),
        max_days_back=int(_getenv("MAX_DAYS_BACK", "35")),
        expand_step_days=int(_getenv("EXPAND_STEP_DAYS", "7")),
        crossref_rows_per_journal=int(_getenv("CROSSREF_ROWS_PER_JOURNAL", "50")),
        crossref_rows_per_author=int(_getenv("CROSSREF_ROWS_PER_AUTHOR", "10")),
        journal_preset=_getenv("JOURNAL_PRESET", DEFAULT_JOURNAL_PRESET),
        crossref_mailto=_getenv("CROSSREF_MAILTO", ""),
        ncbi_email=_getenv("NCBI_EMAIL", ""),
        ncbi_api_key=_getenv("NCBI_API_KEY", ""),
        ncbi_tool=_getenv("NCBI_TOOL", "genome-editing-literature-tracker"),
        enable_pubmed_enrichment=_getenv_bool("ENABLE_PUBMED_ENRICHMENT", True),
        pubmed_max_retries=int(_getenv("PUBMED_MAX_RETRIES", "4")),
        pubmed_backoff_factor=float(_getenv("PUBMED_BACKOFF_FACTOR", "1.0")),
    )
