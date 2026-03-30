from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from app.config import Config
from app.keywords import FAST_FOLLOWER_TYPES, LANE_OPTIONS, TOPIC_TERMS
from app.models import Article, LLMReview, PrescoreResult


REVIEW_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "name": "genome_editing_tracker_review",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "llm_priority": {"type": "integer", "minimum": 0, "maximum": 100},
            "lane": {
                "type": "string",
                "enum": LANE_OPTIONS,
            },
            "key_topics": {
                "type": "array",
                "items": {"type": "string", "enum": TOPIC_TERMS},
                "minItems": 1,
                "maxItems": 5,
            },
            "paper_tldr_5_lines": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 5,
                "maxItems": 5,
            },
            "why_it_matters_to_our_lab": {"type": "string"},
            "technical_takeaway": {"type": "string"},
            "best_fast_follower_title": {"type": "string"},
            "best_fast_follower_rationale": {"type": "string"},
            "fast_follower_type": {
                "type": "string",
                "enum": FAST_FOLLOWER_TYPES,
            },
            "first_experiment": {"type": "string"},
            "time_to_first_readout_weeks": {"type": "integer", "minimum": 1, "maximum": 52},
            "resource_intensity": {
                "type": "string",
                "enum": ["low", "medium", "high"],
            },
            "ff_score": {"type": "integer", "minimum": 0, "maximum": 100},
            "ff_rank": {"type": "string", "enum": ["S", "A", "B", "C"]},
            "share_blurb_1line": {"type": "string"},
            "red_flags": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 6,
            },
            "decision": {"type": "string", "enum": ["priority", "watch", "drop"]},
        },
        "required": [
            "llm_priority",
            "lane",
            "key_topics",
            "paper_tldr_5_lines",
            "why_it_matters_to_our_lab",
            "technical_takeaway",
            "best_fast_follower_title",
            "best_fast_follower_rationale",
            "fast_follower_type",
            "first_experiment",
            "time_to_first_readout_weeks",
            "resource_intensity",
            "ff_score",
            "ff_rank",
            "share_blurb_1line",
            "red_flags",
            "decision",
        ],
        "additionalProperties": False,
    },
}


class LLMReviewer:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.client = OpenAI(api_key=config.openai_api_key)

    def review(self, article: Article, prescore: PrescoreResult) -> LLMReview:
        prompt = build_review_prompt(article, prescore, self.config.reader_language)
        response = self.client.responses.create(
            model=self.config.openai_model,
            input=[
                {"role": "system", "content": build_system_prompt(self.config.reader_language)},
                {"role": "user", "content": prompt},
            ],
            reasoning={"effort": self.config.openai_reasoning_effort},
            text={
                "verbosity": self.config.openai_text_verbosity,
                "format": REVIEW_SCHEMA,
            },
            store=False,
        )
        output_text = getattr(response, "output_text", None)
        if not output_text:
            raise RuntimeError("OpenAI response did not contain output_text")
        payload = json.loads(output_text)
        return LLMReview(**payload)


def build_system_prompt(reader_language: str) -> str:
    language_rule = build_language_rule(reader_language)
    return f"""You are a senior literature analyst for a genome editing and molecular engineering lab.
Your job is not to produce a generic summary. Your job is to convert a paper into an actionable reading card and a fast-follower decision.

This tracker is genome-editing-first, not mtDNA-only.
Prioritize broad genome editing relevance:
- CRISPR/Cas systems
- base editing and prime editing
- TALEN / zinc-finger / programmable nuclease platforms
- editor engineering, specificity, off-target behavior, structural biology
- delivery, compact editors, translational strategy
- mitochondrial editing as one important subdomain, not the only one

The tracker uses a boolean gate first: papers pass because desired keywords or watched-author signals appear in title, keyword metadata, or watch-author logic. The numeric score is for ranking, not for hard filtering.
Reward papers that change how a lab would design an editor, choose a delivery strategy, interpret off-target behavior, or launch a fast-follower experiment.
Do not overvalue prestige or mitochondria alone.
The paper_tldr_5_lines field must contain exactly five concise lines.
The key_topics field must choose only from the allowed controlled vocabulary.
The best_fast_follower_title must be specific and executable.
The first_experiment must be a real first experiment, not a vague strategy statement.
{language_rule}
""".strip()


def build_language_rule(reader_language: str) -> str:
    if reader_language.lower().startswith("ko"):
        return (
            "All reader-facing prose must be written in Korean. "
            "This includes paper_tldr_5_lines, why_it_matters_to_our_lab, technical_takeaway, "
            "best_fast_follower_title, best_fast_follower_rationale, first_experiment, share_blurb_1line, and red_flags. "
            "Keep gene, protein, editor, assay, and journal names in their standard English notation when that is clearer. "
            "Write for a Korean-speaking research team reading in Notion: short sentences, low fluff, immediately skimmable. "
            "Each TL;DR line should be one sentence. why_it_matters_to_our_lab should be 2-4 Korean sentences. "
            "technical_takeaway should be 2-3 Korean sentences. best_fast_follower_rationale should be 2-4 Korean sentences. "
            "first_experiment should be 2-4 Korean sentences with a concrete readout. share_blurb_1line should be one crisp Korean sentence."
        )
    return "Write all reader-facing prose in clear, skimmable English."


def build_review_prompt(article: Article, prescore: PrescoreResult, reader_language: str) -> str:
    authors = ", ".join(article.authors[:12]) if article.authors else ""
    corresponding_authors = ", ".join(article.corresponding_authors[:8]) if article.corresponding_authors else "N/A"
    watched_authors = ", ".join(article.watch_author_matches[:8]) if article.watch_author_matches else "N/A"
    watch_basis = ", ".join(article.watch_author_match_basis[:8]) if article.watch_author_match_basis else "N/A"
    published = article.published.isoformat() if article.published else "unknown"
    abstract = article.abstract or "No abstract available. Infer cautiously from title, keywords, and metadata only."
    controlled_topics = ", ".join(TOPIC_TERMS)
    keyword_list = ", ".join(article.keywords[:25]) if article.keywords else "N/A"

    reader_hint = (
        "Reader language for Notion output: Korean (ko). "
        "The team wants all long-form reading fields in Korean so they can skim quickly in Notion. "
        "Do not translate technical entity names unnaturally; retain standard English scientific terms where clearer."
        if reader_language.lower().startswith("ko")
        else "Reader language for Notion output: English."
    )

    return f"""
Lab objective:
- Maintain a high-impact literature tracker for genome editing, editor engineering, delivery, and mitochondrial editing/biology.
- Surface papers that are worth sharing across the lab, not just mtDNA-specific papers.
- Convert each paper into a short review and one strong fast-follower idea.

Paper metadata:
- Title: {article.title}
- Journal: {article.journal}
- Published: {published}
- DOI: {article.doi or 'N/A'}
- PMID: {article.pmid or 'N/A'}
- Authors: {authors or 'N/A'}
- Corresponding author candidates: {corresponding_authors}
- Watch-author matches: {watched_authors}
- Watch-author basis: {watch_basis}
- Keywords: {keyword_list}
- Source tags: {', '.join(article.source_tags) if article.source_tags else 'N/A'}

Gate and rank context:
- Lane: {prescore.lane}
- Rank score: {prescore.score}
- Gate matches: {', '.join(prescore.gate_matches) if prescore.gate_matches else 'None'}
- Matched keywords across title/keywords/abstract: {', '.join(prescore.matched_keywords) if prescore.matched_keywords else 'None'}
- Bucket scores: {prescore.bucket_scores}

Abstract:
{abstract}

Instructions:
1. Judge this paper from the standpoint of a lab-wide actionable recommender.
2. Prioritize genome editing leverage first; treat mitochondria as an important but not mandatory subdomain.
3. Prefer fast-followers that can create a first readout quickly and leverage existing genome editing / editor engineering capabilities.
4. Be concrete about the first experiment.
5. If the paper is conceptually interesting but not actionable, lower ff_score even if llm_priority remains decent.
6. key_topics must be chosen only from this controlled list: {controlled_topics}
7. Lane should usually stay aligned with the existing gate context unless there is a strong reason to change it.
8. {reader_hint}
9. Make the result easy to skim in Notion within 10-20 seconds.
""".strip()
